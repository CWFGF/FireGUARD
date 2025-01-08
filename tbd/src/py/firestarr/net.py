import datetime
import os
import ssl
import time
import urllib.parse
from functools import cache
from io import StringIO
from urllib.error import HTTPError

import dateutil
import dateutil.parser
import requests
import tqdm_util
from common import (
    FLAG_DEBUG,
    always_false,
    do_nothing,
    ensure_dir,
    ensures,
    fix_timezone_offset,
    locks_for,
    logging,
)
from redundancy import call_safe
from urllib3.exceptions import InsecureRequestWarning

# So HTTPS transfers work properly
ssl._create_default_https_context = ssl._create_unverified_context

# Suppress only the single warning from urllib3 needed.
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

VERIFY = False
# VERIFY = True

# pretend to be something else so servers don't block requests
HEADERS = {
    "User-Agent": " ".join(
        [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "AppleWebKit/537.36 (KHTML, like Gecko)",
            "Chrome/106.0.0.0 Safari/537.36 Edg/106.0.1370.34",
        ]
    ),
}
# HEADERS = {'User-Agent': 'WeatherSHIELD/0.93'}
RETRY_MAX_ATTEMPTS = 0
RETRY_DELAY = 2

# HACK: list of url parameters to not mask
#   just to make sure we mask everything unless we know it's safe in logs
SAFE_PARAMS = [
    "model",
    "lat",
    "lon",
    "ens_val",
    "where",
    "outFields",
    "f",
    "outStatistics",
]
MASK_PARAM = "#######"
WAS_MASKED = set()

CACHE_DOWNLOADED = {}
CACHE_LOCK_FILE = "firestarr_cache"


def _save_http_uncached(
    url,
    save_as,
    fct_is_invalid=always_false,
):
    modlocal = None
    logging.debug(f"Opening {url}")
    response = requests.get(
        url,
        stream=True,
        verify=VERIFY,
        headers=HEADERS,
    )
    if 200 != response.status_code or fct_is_invalid(response):
        url_masked = mask_url(url)
        error = f"Error saving {save_as} from {url_masked}"
        logging.error(error)
        raise HTTPError(
            url_masked,
            response.status_code,
            error,
            response.headers,
            StringIO(response.text),
        )
    if os.path.isfile(save_as) and "last-modified" in response.headers.keys():
        mod = response.headers["last-modified"]
        modtime = dateutil.parser.parse(mod)
        modlocal = fix_timezone_offset(modtime)
        filetime = os.path.getmtime(save_as)
        filedatetime = datetime.datetime.fromtimestamp(filetime)
        if modlocal == filedatetime:
            return save_as
    ensure_dir(os.path.dirname(save_as))
    save_as = tqdm_util.wrap_write(
        response.iter_content(chunk_size=4096),
        save_as,
        "wb",
        desc=url.split("?")[0] if "?" in url else url,
        total=int(response.headers.get("content-length", 0)),
    )
    if modlocal is not None:
        tt = modlocal.timetuple()
        usetime = time.mktime(tt)
        os.utime(save_as, (usetime, usetime))
    return save_as


@cache
def _save_http_cached(
    url,
    save_as,
    fct_is_invalid=always_false,
):
    return call_safe(_save_http_uncached, url, save_as, fct_is_invalid)


def check_downloaded(path):
    # logging.debug(f"check_downloaded({path}) - waiting")
    with locks_for(CACHE_LOCK_FILE):
        # FIX: should return False if file no longer exists
        # logging.debug(f"check_downloaded({path}) - checking")
        result = CACHE_DOWNLOADED.get(path, None)
        # logging.debug(f"check_downloaded({path}) - returning {result}")
        return result


def mark_downloaded(path, flag=True):
    # logging.debug(f"mark_downloaded({path}, {flag})")
    if not (flag and path in CACHE_DOWNLOADED):
        # logging.debug(f"mark_downloaded({path}, {flag}) - waiting")
        with locks_for(CACHE_LOCK_FILE):
            # logging.debug(f"mark_downloaded({path}, {flag}) - marking")
            if flag:
                # logging.debug(f"mark_downloaded({path}, {flag}) - adding")
                CACHE_DOWNLOADED[path] = path
            elif path in CACHE_DOWNLOADED:
                # logging.debug(f"mark_downloaded({path}, {flag}) - removing")
                del CACHE_DOWNLOADED[path]
    # else:
    #     logging.debug(f"mark_downloaded({path}, {flag}) - do nothing")
    # logging.debug(f"mark_downloaded({path}, {flag}) - returning {path}")
    return path


def save_http(
    url,
    save_as,
    keep_existing,
    fct_pre_save,
    fct_post_save,
    fct_is_invalid=always_false,
):
    logging.debug(f"save_http({url}, {save_as})")

    @ensures(
        paths=save_as,
        remove_on_exception=True,
        replace=not keep_existing,
        msg_error=f"Failed getting {url}",
    )
    def do_save(_):
        # if another thread downloaded then don't do it again
        # @ensures already checked if file exists but we want to replace
        # logging.debug(f"do_save({_})")
        r = check_downloaded(_)
        if r:
            # logging.debug(f"{_} was downloaded already")
            return r
        # HACK: put in one last lock so it doesn't download twice
        with locks_for(_ + ".tmp"):
            # HACK: one last check for file because it seems like spotwx limits rate of existing files
            if not (keep_existing and os.path.isfile(_)):
                r = _save_http_cached((fct_pre_save or do_nothing)(url), _, fct_is_invalid)
        # logging.debug(f"do_save({_}) - returning {r}")
        # mark_downloaded(_)
        return _

    try:
        # if already downloaded then use existing file
        # if not downloaded then try to save but check cache before downloading
        # either way, call fct_post_save on the file
        r = check_downloaded(save_as)
        if not r:
            # logging.debug(f"save_http({url}, {save_as}) - calling do_save({save_as})")
            r = do_save(save_as)
            # might have already existed, so marking in do_save() might not happen
            r = mark_downloaded(r)
        # else:
        #     logging.debug(f"save_http({url}, {save_as}) - {save_as} was downloaded")
        r = (fct_post_save or do_nothing)(r)
        # logging.debug(f"save_http({url}, {save_as}) - returning {r}")
        if not check_downloaded(save_as):
            raise RuntimeError(f"Expected {save_as} to be marked as downloaded")
        return r
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.debug(ex)
        # @ensures should have taken care of delting file
        mark_downloaded(save_as, False)
        raise ex


def mask_url(url):
    global WAS_MASKED
    r = urllib.parse.urlparse(url)
    if not FLAG_DEBUG and r.query:
        args = urllib.parse.parse_qs(r.query)
        for k in args.keys():
            if k not in SAFE_PARAMS:
                WAS_MASKED.add(k)
                args[k] = [MASK_PARAM]
        r = r._replace(query="&".join(f"{k}={','.join(v)}" for k, v in args.items()))
    return urllib.parse.urlunparse(r)


def try_save_http(
    url,
    save_as,
    keep_existing,
    fct_pre_save,
    fct_post_save,
    max_save_retries=RETRY_MAX_ATTEMPTS,
    check_code=False,
    fct_is_invalid=always_false,
):
    save_tries = 0
    while True:
        try:
            return save_http(url, save_as, keep_existing, fct_pre_save, fct_post_save, fct_is_invalid)
        except KeyboardInterrupt as ex:
            raise ex
        except Exception as ex:
            logging.info(f"Caught {ex} in {__name__}")
            if isinstance(ex, KeyboardInterrupt):
                raise ex
            m = mask_url(url)
            # no point in retrying if URL doesn't exist or is forbidden
            if check_code and isinstance(ex, HTTPError) and ex.code in [403, 404]:
                # if we're checking for code then return None since file can't exist
                with locks_for(CACHE_LOCK_FILE):
                    CACHE_DOWNLOADED[save_as] = None
                return None
            if FLAG_DEBUG or save_tries >= max_save_retries:
                logging.error(f"Downloading {m} to {save_as} - Failed after {save_tries} attempts")
                raise ex
            logging.warning(f"Downloading {m} to {save_as} - Retrying after:\n\t{ex}")
            time.sleep(RETRY_DELAY)
            save_tries += 1
