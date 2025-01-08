"""Shared code"""

import configparser
import datetime
import inspect
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from functools import cache, wraps
from logging import getLogger

import numpy as np
import pandas as pd
import psutil
import tqdm_util
from dateutil.tz import tzoffset
from filelock import FileLock
from log import logging
from osgeo import gdal
from redundancy import call_safe, get_stack

FLAG_IGNORE_PERIM_OUTPUTS = True
FLAG_DEBUG = True
FLAG_DEBUG_LOCKS = True
FLAG_SAVE_PREPARED = False

FMT_DATETIME = "%Y-%m-%d %H:%M:%S"
FMT_DATE_YMD = "%Y%m%d"
FMT_TIME = "%H%M"
FMT_FILE_MINUTE = "%Y%m%d_%H%M"
FMT_FILE_SECOND = "%Y%m%d_%H%M_%S"

# makes groups that are too big because it joins mutiple groups into a chain
# DEFAULT_GROUP_DISTANCE_KM = 60
# also too big
# DEFAULT_GROUP_DISTANCE_KM = 40
DEFAULT_GROUP_DISTANCE_KM = 20
# MAX_NUM_DAYS = 3
# MAX_NUM_DAYS = 7
MAX_NUM_DAYS = 14
# DEFAULT_M3_LAST_ACTIVE = None
DEFAULT_M3_LAST_ACTIVE = datetime.timedelta(days=30)
DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS = 1
DEFAULT_LAST_ACTIVE_SINCE_OFFSET = None

CURRENT_YEAR_ONLY = False

WX_MODEL = "geps"
FILE_CURRENT = f"/appl/data/{WX_MODEL}_current"
FILE_LATEST = f"/appl/data/{WX_MODEL}_latest"

PUBLISH_AZURE_WAIT_TIME_SECONDS = 10

FORMAT_OUTPUT = "COG"
# FORMAT_OUTPUT = "GTiff"

USE_CWFIS_SERVICE = False
TIMEDELTA_DAY = datetime.timedelta(days=1)
TIMEDELTA_HOUR = datetime.timedelta(hours=1)

CREATION_OPTIONS = [
    "COMPRESS=LZW",
    "TILED=YES",
    "BLOCKSIZE=512",
    # # doesn't work
    # "PREDICTOR=YES",
    "BIGTIFF=YES",
    "OVERVIEW_RESAMPLING=AVERAGE",
    "OVERVIEWS=AUTO",
    # # incredibly slow
    # "TILING_SCHEME=GoogleMapsCompatible",
    "NUM_THREADS=ALL_CPUS",
]
WANT_DATES = [1, 2, 3, 7, 14]

# was still getting messages that look like they're from gdal when debug is on, but
# maybe they're from a package that's using it?

gdal.UseExceptions()
gdal.SetConfigOption("CPL_LOG", "/dev/null")
gdal.SetConfigOption("CPL_DEBUG", "OFF")
gdal.PushErrorHandler("CPLQuietErrorHandler")

getLogger("gdal").setLevel(logging.WARNING)
getLogger("fiona").setLevel(logging.WARNING)

# bounds to use for clipping data
BOUNDS = None

# file to load settings from
SETTINGS_FILE = None
PREFERRED_SETTINGS_FILE = r"../data/config"
DEFAULT_SETTINGS_FILE = r"../config"
# loaded configuration
CONFIG = None

DEFAULT_FILE_LOG_LEVEL = logging.DEBUG
# DEFAULT_FILE_LOG_LEVEL = logging.INFO


def ensure_dir(dir):
    """!
    Check if directory exists and make it if not
    @param dir Directory to ensure existence of
    @return None
    """
    # HACK: azure container is somehow making files instead of directories
    if os.path.isfile(dir):
        try_remove(dir, force=True)
    call_safe(os.makedirs, dir, exist_ok=True)
    if not os.path.isdir(dir):
        logging.fatal("Could not create directory {}".format(dir))
        sys.exit(-1)
    return dir


CELL_SIZE = 100

DIR_SRC_PY_FIRSTARR = os.path.dirname(__file__)
DIR_SRC_PY = os.path.dirname(DIR_SRC_PY_FIRSTARR)
DIR_SRC_PY_CFFDRSNG = os.path.join(DIR_SRC_PY, "cffdrs-ng")
sys.path.append(DIR_SRC_PY_CFFDRSNG)

DIR_TBD = "/appl/tbd"
FILE_TBD_BINARY = os.path.join(DIR_TBD, "tbd")
FILE_TBD_SETTINGS = os.path.join(DIR_TBD, "settings.ini")
DIR_SCRIPTS = os.path.join(DIR_TBD, "scripts")
FILE_SIM_LOG = "firestarr.log"

DIR_DATA = ensure_dir(os.path.abspath("/appl/data"))
DIR_DOWNLOAD = ensure_dir(os.path.join(DIR_DATA, "download"))
DIR_EXTRACTED = ensure_dir(os.path.join(DIR_DATA, "extracted"))
DIR_GENERATED = ensure_dir(os.path.join(DIR_DATA, "generated"))
DIR_INTERMEDIATE = os.path.join(DIR_DATA, "intermediate")
DIR_LOG = ensure_dir(os.path.join(DIR_DATA, "logs"))
DIR_OUTPUT = ensure_dir(os.path.join(DIR_DATA, "output"))
DIR_RASTER = ensure_dir(os.path.join(DIR_GENERATED, "grid", f"{CELL_SIZE}m"))
DIR_RUNS = ensure_dir(os.path.join(DIR_DATA, "runs"))
DIR_SIMS = ensure_dir(os.path.join(DIR_DATA, "sims"))
SUBDIR_CURRENT = "current"
# DIR_TMP = ensure_dir(os.path.join(DIR_DATA, "tmp"))
# should be better to not use container for temporary files?
DIR_SYS_TMP = os.environ.get("TEMP") or "/tmp"
DIR_TMP = ensure_dir(os.path.join(DIR_SYS_TMP, "firestarr"))
DIR_LOCKS = ensure_dir(os.path.join(DIR_TMP, "locks"))

DIR_ZIP = ensure_dir(os.path.join(DIR_DATA, "zip"))

MINUTES_PER_HOUR = 60
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = MINUTES_PER_HOUR * SECONDS_PER_MINUTE

DEFAULT_BOUNDS = "bounds.geojson"

FILE_LOCK_PUBLISH = os.path.join(DIR_OUTPUT, "publish")
FILE_LOCK_PREPUBLISH = os.path.join(DIR_OUTPUT, "prepublish")
FILE_LOCK_MODEL = os.path.join(DIR_OUTPUT, "model")


def listdir_sorted(path, ignore_locks=True):
    paths = []
    if os.path.exists(path):
        paths = sorted(os.listdir(path))
        if ignore_locks:
            paths = [x for x in paths if not x.endswith(".lock")]
    return paths


def list_dirs(path):
    return [x for x in listdir_sorted(path) if os.path.isdir(os.path.join(path, x))]


def is_newer_than(file_new, file_old):
    if not os.path.isfile(file_old):
        # always newer if nothing exists
        return True
    time_new = os.path.getmtime(file_new)
    time_old = os.path.getmtime(file_old)
    return time_new > time_old


def to_utc(d):
    return pd.to_datetime(d, errors="coerce", utc=True)


def read_config(force=False):
    """!
    Read configuration from default file
    @param force Force reading even if already loaded
    @return None
    """
    global CONFIG
    global BOUNDS
    if os.path.isfile(PREFERRED_SETTINGS_FILE):
        SETTINGS_FILE = PREFERRED_SETTINGS_FILE
    else:
        SETTINGS_FILE = DEFAULT_SETTINGS_FILE
    logging.info("Reading config file {}".format(SETTINGS_FILE))
    if force or CONFIG is None:
        # default to all of canada
        CONFIG = {
            "BOUNDS_LATITUDE_MIN": "41",
            "BOUNDS_LATITUDE_MAX": "84",
            "BOUNDS_LONGITUDE_MIN": "-141",
            "BOUNDS_LONGITUDE_MAX": "-52",
            # use bounds from local directory if not specified
            "BOUNDS_FILE": DEFAULT_BOUNDS,
            "SPOTWX_API_KEY": "",
            "SPOTWX_API_LIMITs": "150",
            "AZURE_URL": "",
            "AZURE_TOKEN": "",
            "AZURE_CONTAINER": "",
            "GEOSERVER_LAYER": "",
            "GEOSERVER_COVERAGE": "",
            "GEOSERVER_CREDENTIALS": "",
            "GEOSERVER_SERVER": "",
            "GEOSERVER_WORKSPACE": "",
            "GEOSERVER_DIR_DATA": "",
        }
        config = configparser.ConfigParser()
        # set default values and then read to overwrite with whatever is in config
        config.add_section("GLOBAL")
        for k, v in CONFIG.items():
            config.set("GLOBAL", k, v)
        try:
            with open(SETTINGS_FILE) as configfile:
                # fake a config section so it works with parser
                config.read_file(itertools.chain(["[GLOBAL]"], configfile), source=SETTINGS_FILE)
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            logging.info("Creating new config file {}".format(SETTINGS_FILE))
            # HACK: don't output section header because it breaks bash
            from io import StringIO

            buffer = StringIO()
            config.write(buffer)
            buffer.seek(0)
            fixed = []
            # skip header and last empty line
            for line in buffer.readlines()[1:-1]:
                split = line.strip("\n").split(" = ")
                # HACK: if for some reason the value has " = " in it then 2 < len(split)
                k = split[0]
                v = " = ".join(split[1:])
                fixed.append(f"{k.upper()}={v}\n")
            with open(SETTINGS_FILE, "w") as f:
                f.writelines(fixed)
        # assign to CONFIG so defaults get overwritten
        for k, v in config.items("GLOBAL"):
            v = v.strip('"') if v.startswith('"') and v.endswith('"') else v.strip("'")
            CONFIG[k.upper()] = v
        file_bounds = CONFIG["BOUNDS_FILE"]
        if not os.path.isfile(file_bounds):
            if DEFAULT_BOUNDS != file_bounds:
                logging.warning(f"Bounds specified as {file_bounds} but not found - " f"reverting to {DEFAULT_BOUNDS}")
                file_bounds = DEFAULT_BOUNDS
        if not os.path.isfile(file_bounds):
            if DEFAULT_BOUNDS == file_bounds:
                logging.fatal("Default bounds specified but file does not exist")
                raise RuntimeError("Default bounds specified but file does not exist")
        BOUNDS = {
            "latitude": {
                "min": float(CONFIG["BOUNDS_LATITUDE_MIN"]),
                "max": float(CONFIG["BOUNDS_LATITUDE_MAX"]),
            },
            "longitude": {
                "min": float(CONFIG["BOUNDS_LONGITUDE_MIN"]),
                "max": float(CONFIG["BOUNDS_LONGITUDE_MAX"]),
            },
            "bounds": file_bounds,
        }
        for k in ["latitude", "longitude"]:
            high, low = BOUNDS[k]["max"], BOUNDS[k]["min"]
            BOUNDS[k]["mid"] = (high - low) / 2 + low


# HACK: need to do this every time file is loaded or else threads might get to it first
read_config()


def fix_timezone_offset(d):
    """!
    Convert from UTC to local time, respecting DST if required
    @param d Date to fix timezone offset for
    @return Date converted to local time
    """
    local_offset = time.timezone
    if time.daylight:
        if time.localtime().tm_isdst > 0:
            local_offset = time.altzone
    localdelta = datetime.timedelta(seconds=-local_offset)
    # convert to local time so other ftp programs would produce same result
    return (d + localdelta).replace(tzinfo=None)


def copy_file(filename, toname):
    """!
    Copy file and keep timestamp the same
    @param filename Source path to copy from
    @param toname Destination path to copy to
    @return None
    """
    shutil.copyfile(filename, toname)
    filetime = os.path.getmtime(filename)
    os.utime(toname, (filetime, filetime))


def filterXY(data):
    data = data[data[:, :, 0] >= BOUNDS["latitude"]["min"]]
    data = data[data[:, 0] <= BOUNDS["latitude"]["max"]]
    data = data[data[:, 1] >= BOUNDS["longitude"]["min"]]
    data = data[data[:, 1] <= BOUNDS["longitude"]["max"]]
    return data


def try_remove(paths, verbose=False, force=False):
    """!
    Delete path but ignore errors if can't while raising old error
    @param path Path to delete
    @return None
    """
    if paths:
        paths = ensure_string_list(paths)
        for path in paths:
            # remove locks even if debugging
            # if not FLAG_DEBUG or path.endswith(".lock"):
            if force or not FLAG_DEBUG:
                try:
                    if os.path.isfile(path):
                        if verbose:
                            logging.debug("Trying to delete file {}".format(path))
                        os.remove(path)
                    elif os.path.isdir(path):
                        if verbose:
                            logging.debug("Trying to remove directory {}".format(path))
                        shutil.rmtree(path, ignore_errors=True)
                except KeyboardInterrupt as ex:
                    raise ex
                except Exception:
                    pass


def force_remove(paths, verbose=True):
    return try_remove(paths, verbose=verbose, force=True)


def in_sim_folder(path):
    if DIR_RUNS in path:
        return path.replace(DIR_RUNS, DIR_SIMS)
    if DIR_SIMS in path:
        return path
    raise RuntimeError(f"Trying to find sim folder for invalid path {path}")


def in_run_folder(path):
    if DIR_SIMS in path:
        return path.replace(DIR_SIMS, DIR_RUNS)
    if DIR_RUNS in path:
        return path
    raise RuntimeError(f"Trying to find run folder for invalid path {path}")


def split_line(line):
    """!
    Split given line on whitespace sections
    @param line Line to split on whitespace
    @return Array of strings after splitting
    """
    return re.sub(r" +", " ", line.strip()).split(" ")


def unzip(path, to_dir, match=None):
    if not os.path.exists(to_dir):
        os.mkdir(to_dir)
    with zipfile.ZipFile(path, "r") as zip_ref:
        if match is None:
            names = zip_ref.namelist()
            zip_ref.extractall(to_dir)
        else:
            names = [x for x in zip_ref.namelist() if match in x]
            zip_ref.extractall(to_dir, names)
    return [os.path.join(to_dir, x) for x in names]


def start_process(run_what, cwd):
    """!
    Start running a command using subprocess
    @param run_what Process to run
    @param flags Flags to run with
    @param cwd Directory to run in
    @return Running subprocess
    """
    # logging.debug(run_what)
    p = subprocess.Popen(run_what, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    p.args = run_what
    p.cwd = cwd
    return p


def finish_process(process):
    stdout, stderr = [x.decode("utf-8") for x in process.communicate()]
    if process.returncode != 0:
        # HACK: seems to be the exit code for ctrl + c events loop tries to run
        # it again before it exits without this
        if -1073741510 == process.returncode:
            sys.exit(process.returncode)
        raise RuntimeError(
            f"Error running {process.args} in {process.cwd} [{process.returncode}]: {stderr[:20]}\n{stdout[:20]}"
        )
        # raise RuntimeError(f"Error code {process.returncode} running {process.args}")
    return stdout, stderr


def run_process(*args, **kwargs):
    return finish_process(start_process(*args, **kwargs))


def zip_folder(zip_name, path, ignore_locks=True):
    with zipfile.ZipFile(zip_name, "w") as zf:
        all_files = []
        logging.info("Finding files")
        for root, dirs, files in os.walk(path):
            for d in dirs:
                dir = os.path.join(root, d)
                zf.write(dir, dir.replace(path, "").lstrip("/"))
            for f in files:
                all_files.append(os.path.join(root, f))
        logging.info("Zipping")
        for f in tqdm_util.apply(all_files, desc=os.path.basename(zip_name)):
            f_relative = f.replace(path, "").lstrip("/")
            if not f_relative.endswith(".lock") or not ignore_locks:
                zf.write(f, f_relative, zipfile.ZIP_DEFLATED)
        return zip_name


def dump_json(data, path):
    dir_out = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    file = os.path.join(dir_out, f"{base}.json")

    @ensures(paths=file, remove_on_exception=True)
    def fct_create(_):
        # NOTE: json.dumps() first and then write string so
        #      file is okay if dump fails
        # FIX: this is overkill but just want it to work for now
        s = json.dumps(data)
        json.loads(s)
        with open(_, "w") as f:
            # HACK: not getting full string when using f.write(s)
            json.dump(data, f)
            # f.write(s)
        return _

    return call_safe(fct_create, file)


def read_json_safe(path):
    def do_read(_):
        with open(_) as f:
            return json.load(f)

    return call_safe(do_read, path)


def pick_max(a, b):
    return np.max(list(zip(a, b)), axis=1)


def pick_max_by_column(a, b, column, index=None):
    # these need to match, so assume index of a if not specified
    if index is None:
        index = a.index
    return pick_max(a.loc[index, column], b.loc[index, column])


# standard function we can use as a default wrapper if nothing special happens
def do_nothing(x, *args, **kwargs):
    return x


@cache
def calc_offset(d, i):
    return d + datetime.timedelta(days=i)


class Origin(object):
    def __init__(self, d=None):
        if d is None:
            d = datetime.date.today()
        else:
            d = pd.to_datetime(d)
        # HACK: don't check for class because hopefully this works with anything
        if hasattr(d, "date"):
            if callable(d.date):
                d = d.date()
            else:
                d = d.date
        self._today = d

    def offset(self, i):
        return calc_offset(self._today, i)

    @property
    def today(self):
        return self._today

    @property
    def yesterday(self):
        return self.offset(-1)

    @property
    def tomorrow(self):
        return self.offset(1)


@contextmanager
def log_on_entry_exit(msg, logger=logging):
    logger.info(f"START - {msg}")
    yield
    # 3 spaces after END so we line up like:
    #   START -
    #   END   -
    logger.debug(f"END   - {msg}")


DEFAULT_MKDIRS = True


def ensure_string_list(paths):
    """Make sure that we have a list of strings and convert single string to list"""
    if not paths:
        raise RuntimeError("Expected paths but got {paths}")
    # HACK: strings are iterable, so can't just check if that works
    if isinstance(paths, str):
        # make into a list no matter what so code is same
        return [paths]
    list_paths = []
    for path in paths:
        # iterate to make sure it's all strings and turn into a list
        if not isinstance(path, str):
            raise RuntimeError(f"Expected paths to be strings but got {paths}")
        list_paths.append(path)
    return list_paths


DEFAULT_LOCK_TIMEOUT = -1
# DEFAULT_LOCK_TIMEOUT = 5


# make an object so that when program ends all the file locks should get cleaned up
class LockTracker(object):
    def __init__(self) -> None:
        self._lock_files = set()

    def get_lock(self, path):
        # HACK: keep locks out of directories that might be in azure
        # file_lock = os.path.join(DIR_LOCKS, path + ".lock")
        # os.path.join() doesn't work if path starts with '/' ?
        file_lock = f"{DIR_LOCKS}/{path.strip('/')}.lock"
        ensure_dir(os.path.dirname(file_lock))
        logging.debug(f"Getting lock for '{path}' as '{file_lock}'")
        self._lock_files.add(file_lock)
        return FileLock(file_lock, DEFAULT_LOCK_TIMEOUT, thread_local=False)

    def __del__(self) -> None:
        print(f"Removing locks on exit:\n\t{self._lock_files}")
        try_remove(list(self._lock_files))


LOCK_TRACKER = LockTracker()


@contextmanager
def locks_for(paths):
    paths = ensure_string_list(paths)
    try:
        # FIX: deadlocks if same thread thread tries to get same file
        attempted_locks = [LOCK_TRACKER.get_lock(path) for path in paths]
        locks = []
        for lock in attempted_locks:
            try:
                call_safe(lock.acquire)
                locks.append(lock)
            except FileNotFoundError:
                if FLAG_DEBUG_LOCKS:
                    logging.debug(f"FileNotFoundError for {lock.lock_file}")
                # lock is missing, so must have been deleted
                pass
            except Exception as ex:
                if FLAG_DEBUG_LOCKS:
                    logging.debug(f"Exception for {lock.lock_file}")
                logging.error(get_stack(ex))
        yield locks
    finally:
        for lock in locks:
            # HACK: is this causing the errors about deleting locks
            try:
                if FLAG_DEBUG_LOCKS:
                    logging.debug(f"Releasing lock {lock.lock_file}")
                lock.release()
            except KeyboardInterrupt as ex:
                raise ex
            except Exception as ex:
                if FLAG_DEBUG_LOCKS:
                    logging.debug(f"Exception for {lock.lock_file}")
                    logging.debug(get_stack(ex))
                pass


def paths_exist(paths):
    return np.all([os.path.exists(path) for path in paths])


# maybe these exist but easier to just make them than check for now
def always_false(*args, **kwargs):
    return False


def always_true(*args, **kwargs):
    return True


@contextmanager
def ensure(
    paths,
    fct_create,
    remove_on_exception,
    replace=None,
    msg_error=None,
    mkdirs=DEFAULT_MKDIRS,
    logger=None,
    retries=0,
    can_fail=False,
):
    list_paths = ensure_string_list(paths)
    # turn into a function so we can call it, but allow bools
    if replace is None:
        replace = always_false
    elif isinstance(replace, bool):
        replace = always_true if replace else always_false
    try:
        if mkdirs:
            # if directory doesn't exist then lock file can't be made
            # but don't want to always automatically make it for some reason?
            for path in np.unique([os.path.dirname(p) for p in list_paths]):
                ensure_dir(path)
        # simplify locking because we're trying to access a specific file
        with locks_for(list_paths) as locks:
            result = paths
            # path could be directory or file
            if not paths_exist(list_paths) or replace(list_paths):
                # in case we want to retry
                result = None
                while result is None and retries >= 0:
                    ex_current = None
                    try:
                        # fct is expected to make the path
                        result = fct_create(list_paths)
                        logging.debug(f"fct_create({list_paths}) made {result}")
                    except KeyboardInterrupt as ex:
                        raise ex
                    except Exception as ex:
                        logging.error(ex)
                        logging.error(get_stack(ex))
                        ex_current = ex
                        retries -= 1
                if ex_current is not None:
                    logging.error(f"Raising {ex_current}")
                    # have to remove or why would result change?
                    try_remove(list_paths)
                    # HACK: seems to freeze on retry otherwise?
                    for p in [lock.lock_file for lock in locks]:
                        try_remove(p)
                    raise ex_current
                # HACK: check that it returns what we asked for so we know it's
                #       updated to work properly with this and just return path
                if not (can_fail and result is None) and result != paths:
                    raise RuntimeError(f"Expected function returning {paths} but got {result}")
            if not (can_fail and result is None) and not paths_exist(list_paths):
                raise RuntimeError(f"Expected {list_paths} to exist")
            yield result
            # since the file now exists, we can remove the lock since everything
            # can just read it now
            for lock in locks:
                try:
                    # HACK: maybe getting lock_file is causing the error?
                    try_remove(lock.lock_file)
                except KeyboardInterrupt as ex:
                    raise ex
                except Exception:
                    pass
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        # use default logger if none specified
        if logger is None:
            logger = logging
        logger.debug(
            "\n\t".join(
                [f"Raising {ex}", (msg_error or f"Could not ensure {list_paths}")]
                + ([f"Removing {remove_on_exception}"] if remove_on_exception else [])
            )
        )
        if remove_on_exception:
            try_remove(list_paths)
        raise ex


def ensures(
    paths,
    remove_on_exception,
    fct_process=None,
    replace=None,
    msg_error=None,
    mkdirs=DEFAULT_MKDIRS,
    logger=None,
    retries=0,
    can_fail=False,
):
    def decorator(fct):
        @wraps(fct)
        def wrapper(*args, **kwargs):
            nonlocal retries

            def fct_create(paths):
                return fct(*args, **kwargs)

            # in case we want to retry
            while retries >= 0:
                ex_current = None
                # HACK: do our own retry so we know where it failed
                try:
                    with ensure(
                        paths,
                        fct_create,
                        remove_on_exception=remove_on_exception,
                        replace=replace,
                        msg_error=msg_error,
                        mkdirs=mkdirs,
                        logger=logger,
                        can_fail=can_fail,
                    ):
                        try:
                            return (fct_process or do_nothing)(paths)
                        except KeyboardInterrupt as ex:
                            raise ex
                        except Exception as ex:
                            # failed parsing file
                            ex_current = ex
                            logging.error(f"Failed parsing {paths} so removing and retrying")
                            force_remove(paths)
                except KeyboardInterrupt as ex:
                    raise ex
                except Exception as ex:
                    logging.error(f"Failed getting file: {ex}")
                    logging.error(get_stack(ex))
                    # failed getting file
                    ex_current = ex
                retries -= 1
            if ex_current is not None:
                raise ex_current

        return wrapper

    return decorator


def make_show_args(fct, show_args, ignore_args=["self"]):
    if callable(show_args):
        # if it's already a function then use it
        return show_args

    def show_args_none(*args, **kwargs):
        return ""

    params = inspect.signature(fct).parameters
    had_self = "self" in params.keys()
    check_args = [x for x in params.keys() if x not in ignore_args]

    if show_args and show_args is not True:
        # filter args to match this list
        check_args = [x for x in check_args if x in show_args]

    # if filtered all args out or was False already
    if not (show_args and check_args):
        # if no arguments then don't try to show them
        return show_args_none

    # always going to be filtered since we make a list excluding some things
    def do_show_args(*args, **kwargs):
        if had_self:
            if "self" not in kwargs.keys():
                # if not named then assume it's first argument
                args = args[1:]
        return ", ".join([f"{x}" for x in args] + [f"{k}={v}" for k, v in kwargs.items() if k in check_args])

    return do_show_args


def log_entry_exit(logger=logging, show_args=True):
    def decorator(fct):
        # use function variable so logic doesn't happen on every call
        call_show = make_show_args(fct, show_args)

        @wraps(fct)
        def wrapper(*args, **kwargs):
            with log_on_entry_exit(f"{fct.__name__}({call_show(*args, **kwargs)})", logger):
                return fct(*args, **kwargs)

        return wrapper

    return decorator


def parse_str_list(s):
    # could just use eval() but want to be safer about it
    if not isinstance(s, str):
        raise RuntimeError(f"Expected string but got {s}")
    if not s.startswith("[") and s.endswith("]"):
        raise RuntimeError(f"Expected list surrounded by [] but got {s}")

    def parse(x):
        if (x.startswith("'") and x.endswith("'")) or (x.startswith('"') and x.endswith('"')):
            # it's a string, so just remove the quotes
            return x[1:-1]
        if re.match("^[0-9]+$", x):
            return int(x)
        # let this fail and throw - don't parse fancy lists
        return float(x)

    return [parse(x.strip()) for x in s[1:-1].split(",")]


def import_cffdrs():
    import NG_FWI as cffdrs

    return cffdrs


cffdrs = import_cffdrs()


def find_ranges_missing(datetime_start, datetime_end, times, freq="H"):
    # determine which times don't exist between start and end time
    times_needed = set(pd.date_range(datetime_start, datetime_end, freq=freq, inclusive="both"))
    if not times_needed:
        return times_needed
    ranges_missing = []
    times_missing = set(times_needed).difference(set(times))
    hr_begin = None
    hr_end = None
    for h in sorted(times_needed):
        if hr_begin is None:
            if h in times_missing:
                ranges_missing.append([h, h])
                hr_begin = h
        else:
            if h not in times_missing:
                if hr_begin is not None and hr_end is not None:
                    # # this hour isn't required, so last hour is end of range
                    # ranges_missing.append(hr_begin, hr_end)
                    hr_begin = None
                    hr_end = None
            else:
                ranges_missing[-1][1] = h
                hr_end = h
    return ranges_missing


def find_missing(df_wx, datetime_start, datetime_end):
    return find_ranges_missing(
        datetime_start,
        datetime_end,
        pd.to_datetime(df_wx["datetime"]) if df_wx is not None else [],
    )


def remove_timezone_utc(d):
    d = pd.to_datetime(d, utc=True)
    if isinstance(d, pd.Timestamp):
        return d.tz_localize(None)
    return [x.tz_localize(None) for x in d]


def tz_from_offset(offset):
    # FIX: must be a better way but just do this for now
    utcoffset_hours = offset.total_seconds() / SECONDS_PER_HOUR
    h, m = abs(int(utcoffset_hours)), int((utcoffset_hours % 1) * MINUTES_PER_HOUR)
    sign = "+" if utcoffset_hours >= 0 else "-"
    return tzoffset(f"Z{sign}{h:02d}{m:02d}", offset)


def is_empty(df):
    return df is None or 0 == len(df)


def to_csv_safe(df, file_csv, *args, **kwargs):
    def do_save(*args, **kwargs):
        return df.to_csv(file_csv, *args, **kwargs)

    return call_safe(do_save, *args, **kwargs)


def read_csv_safe(*args, **kwargs):
    return call_safe(pd.read_csv, *args, **kwargs)


def count_procs(name="tbd"):
    processes = []
    for p in psutil.process_iter():
        try:
            if p.name() == name:
                processes.append(p.as_dict(attrs=["cpu_times", "name", "pid", "status"]))
        except psutil.NoSuchProcess:
            continue
    return len(processes)


def run_after_done(fct, *args, **kwargs):
    while count_procs() > 0:
        time.sleep(10)
    return fct(*args, **kwargs)


# Look for argument in list. Remove and return whether it was there or not
def check_arg(a, args):
    flag = False
    if a in args:
        args.remove(a)
        flag = True
    logging.info(f"Flag for {a} is set to {flag}")
    return flag, args
