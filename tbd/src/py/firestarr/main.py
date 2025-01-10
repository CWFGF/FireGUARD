import datetime
import os
import sys
import time

from common import (
    DEFAULT_FILE_LOG_LEVEL,
    DIR_LOG,
    DIR_OUTPUT,
    FILE_TBD_BINARY,
    FILE_TBD_SETTINGS,
    SECONDS_PER_MINUTE,
    WX_MODEL,
    check_arg,
    logging,
)
from datasources.spotwx import get_model_dir_uncached, set_model_dir
from log import add_log_file
from redundancy import get_stack
from run import Run, make_resume

# NOTE: rotating log file doesn't help because this isn't continuously running
LOG_MAIN = add_log_file(
    os.path.join(DIR_LOG, f"firestarr_{datetime.date.today().strftime('%Y%m%d')}.log"),
    level=DEFAULT_FILE_LOG_LEVEL,
)
logging.info(f"Starting FireSTARR version {os.environ.get('VERSION', 'UNKNOWN')}")
WAIT_WX = SECONDS_PER_MINUTE * 5

sys.path.append(os.path.dirname(sys.executable))
sys.path.append("/usr/local/bin")

did_wait = False
run_current = None
run_attempts = 0
no_retry = False
do_retry = True


def run_main(args):
    global did_wait
    global run_current
    global run_attempts
    global no_retry
    global do_retry

    # HACK: just get some kind of parsing for right now
    do_resume, args = check_arg("--resume", args)
    no_resume, args = check_arg("--no-resume", args)
    if do_resume and no_resume:
        raise RuntimeError("Can't specify --no-resume and --resume")
    # don't use resume arg if running again
    do_resume = do_resume and run_current is None
    no_publish, args = check_arg("--no-publish", args)
    no_merge, args = check_arg("--no-merge", args)
    no_wait, args = check_arg("--no-wait", args)
    no_retry, args = check_arg("--no-retry", args)
    prepare_only, args = check_arg("--prepare-only", args)
    do_retry = False if no_retry else True
    do_publish = False if no_publish else None
    do_merge = False if no_merge else None
    do_wait = not no_wait
    did_wait = False
    if do_wait:

        def wait_and_check_resume():
            global did_wait
            global ran_outdated
            while True:
                dir_model = get_model_dir_uncached(WX_MODEL)
                modelrun = os.path.basename(dir_model)
                # HACK: just trying to check if run used this weather
                prev = make_resume(do_publish=False, do_merge=False)
                if prev is None:
                    return False
                wx_updated = prev._modelrun != modelrun
                if not wx_updated and not prev._published_clean:
                    logging.info("Found previous run and trying to resume")
                    ran_outdated = True
                    # previous run is for same time, but didn't work
                    return True
                if wx_updated:
                    # HACK: need to set this so cache isn't used
                    set_model_dir(dir_model)
                    logging.info(f"Have new weather for {dir_model}")
                    break
                logging.info(f"Previous run already used {modelrun} - " f"waiting {WAIT_WX}s for updated weather")
                did_wait = True
                time.sleep(WAIT_WX)
            # have new weather so don't resume
            return False

        should_resume = wait_and_check_resume()
        logging.info(f"Based on weather and previous run, should_resume == {should_resume}")
    # assume resuming if not waiting
    if no_resume and should_resume:
        logging.warning("Should resume but was told not to, so making new run")
    do_resume = (not no_resume) and (do_resume or (not do_wait) or should_resume)
    if do_resume:
        if 1 < len(args):
            logging.fatal(f"Too many arguments:\n\t {sys.argv}")
        dir_resume = args[0] if args else None
        run_current = make_resume(
            dir_resume,
            do_publish=do_publish,
            do_merge=do_merge,
            prepare_only=prepare_only,
        )
        logging.info(f"Resuming previous run in {run_current._dir_runs}")
    else:
        max_days = int(args[1]) if len(args) > 1 else None
        dir_arg = args[0] if len(args) > 0 else None
        if dir_arg and not os.path.isdir(dir_arg):
            logging.fatal(f"Expected directory but got {dir_arg}")
            sys.exit(-1)
        if dir_arg and DIR_OUTPUT in os.path.abspath(dir_arg):
            if max_days:
                logging.fatal("Cannot specify number of days if resuming")
                sys.exit(-1)
            # if we give it a simulation directory then resume those sims
            run_current = Run(dir=dir_arg, do_publish=do_publish, prepare_only=prepare_only)
            logging.info(f"Resuming simulations in {dir_arg}")
            run_current.check_and_publish()
        else:
            logging.info("Starting new run")
            run_current = Run(
                dir_fires=dir_arg,
                max_days=max_days,
                do_publish=do_publish,
                do_merge=do_merge,
                prepare_only=prepare_only,
            )
    run_attempts += 1
    # returns true if just finished current run
    is_current = run_current.run_until_successful_or_outdated(no_retry=no_retry)
    is_outdated = not is_current
    if prepare_only:
        do_retry = False
        return True
    is_published = run_current._published_clean
    needs_publish = run_current.check_do_publish() and not is_published
    should_rerun = (not no_resume) and (is_outdated or needs_publish)
    logging.info(
        f"Run {run_current._name}:\n\t"
        f"is_outdated = {is_outdated}, is_published = {is_published}, should_rerun = {should_rerun}, no_retry == {no_retry}"
    )
    # whether things should stop running
    return no_retry or (not should_rerun)


if __name__ == "__main__":
    if not os.path.exists(FILE_TBD_BINARY):
        raise RuntimeError(f"Unable to locate simulation model binary file {FILE_TBD_BINARY}")
    if not os.path.exists(FILE_TBD_SETTINGS):
        raise RuntimeError(f"Unable to locate simulation model settings file {FILE_TBD_SETTINGS}")
    logging.info("Called with args %s", str(sys.argv))
    args_orig = sys.argv[1:]
    # rely on argument parsing later
    while do_retry:
        # HACK: just do forever for now since running manually
        logging.info("Attempting update")
        args = args_orig[:]
        try:
            # returns true if just finished current run
            if run_main(args):
                do_retry = False
                break
            logging.info("Trying again because used old weather")
        except KeyboardInterrupt as ex:
            raise ex
        except Exception as ex:
            logging.error(ex)
            logging.error(get_stack(ex))
            if no_retry:
                logging.error("Stopping because of error")
                sys.exit(-1)
            logging.info("Trying again because of error")
    logging.info("Finished successfully")
