from abc import ABC, abstractmethod
from typing import final

import geopandas as gpd
import numpy as np
from gis import CRS_WGS84, make_empty_gdf

COLUMNS_STATION = ["lat", "lon"]
COLUMN_MODEL = "model"
COLUMNS_STREAM = [COLUMN_MODEL, "id"]
COLUMNS_MODEL = COLUMNS_STREAM + COLUMNS_STATION
COLUMN_TIME = "datetime"
COLUMNS_FWI = ["ffmc", "dmc", "dc"]
COLUMNS_WEATHER = ["temp", "rh", "wd", "ws", "prec"]
FIELDS_WEATHER = {
    "key": COLUMNS_MODEL,
    "columns": COLUMNS_WEATHER,
}
COLUMNS = {
    "feature": {"key": [], "columns": []},
    "fire": {"key": ["fire_name"], "columns": ["area", "status"]},
    "fwi": {"key": COLUMNS_STATION, "columns": COLUMNS_FWI},
    "model": FIELDS_WEATHER,
    "hourly": FIELDS_WEATHER,
    "fire_weather": {
        "key": COLUMNS_MODEL,
        "columns": COLUMNS_WEATHER + COLUMNS_FWI,
    },
}


def get_key_and_columns(template):
    t = COLUMNS[template]
    key = t["key"]
    columns = key + [COLUMN_TIME] + t["columns"] + ["geometry"]
    return key, columns


def get_columns(template):
    return get_key_and_columns(template)[1]


def make_template_empty(template):
    return make_empty_gdf(get_columns(template))


def check_columns(df, template):
    key, columns = get_key_and_columns(template)
    try:
        if df is None:
            return make_template_empty(template)
        # sort based on columns in order from left to right
        # logging.debug("reset_index")
        df = df.reset_index()
        # logging.debug("columns")
        df = df[columns]
        if key:
            # logging.debug("set_index")
            df = df.set_index(key).sort_index()
        else:
            # logging.debug("reset_index")
            # renumber rows if no key
            df = df.reset_index(drop=True)
        # logging.debug("sort_values")
        # for some reason sorting on all columns in order doesn't actually sort?
        df = df.sort_values([COLUMN_TIME])
        # HACK: keep everything in WGS84
        if isinstance(df, gpd.GeoDataFrame):
            # logging.debug("to_crs")
            df = df.to_crs(CRS_WGS84)
            # logging.debug("return")
        return df
    except KeyError:
        ERR = "Columns do not match expected columns"
        raise RuntimeError(f"{ERR}\nExpected:\n\t{columns}\nGot:\n\t{df.columns}")


def to_gdf(df, crs=CRS_WGS84):
    return gpd.GeoDataFrame(df, crs=crs, geometry=gpd.points_from_xy(df["lon"], df["lat"], crs=crs))


def make_point(lat, lon, crs=CRS_WGS84):
    # always take lat lon as WGS84 but project to requested crs
    pt = gpd.points_from_xy([lon], [lat], crs=CRS_WGS84)
    if crs != CRS_WGS84:
        pt = gpd.GeoDataFrame(geometry=pt, crs=CRS_WGS84).to_crs(crs).iloc[0].geometry
    return pt


def pick_date_refresh(as_of, refresh):
    # if from a previous date then use that, but if from same day as refresh
    # use refresh time
    return as_of if as_of.date() != refresh.date() else refresh


class Source(ABC):
    def __init__(self, bounds) -> None:
        # this applies to anything in the bounds
        self._bounds = bounds if bounds is None else bounds.dissolve()

    @classmethod
    @property
    @abstractmethod
    def _provides(cls):
        pass

    @property
    def bounds(self) -> gpd.GeoDataFrame:
        # copy so it can't be modified
        return None if self._bounds is None else self._bounds.loc[:]

    @classmethod
    @property
    @final
    def columns(cls):
        return COLUMNS[cls._provides]["columns"]

    @classmethod
    @property
    @final
    def key(cls):
        return COLUMNS[cls._provides]["key"]

    @classmethod
    @final
    def check_columns(cls, df):
        return check_columns(df, cls._provides)

    def applies_to(self, lat, lon) -> bool:
        return self._bounds is None or np.any(self._bounds.contains(make_point(lat, lon, self._bounds.crs)))


class SourceFeature(Source):
    def __init__(self, bounds) -> None:
        super().__init__(bounds)

    @classmethod
    @property
    def _provides(cls):
        return "feature"

    @abstractmethod
    def _get_features(self):
        pass

    @final
    def get_features(self):
        return self.check_columns(self._get_features())


class SourceFire(Source):
    def __init__(self, bounds) -> None:
        super().__init__(bounds)

    @classmethod
    @property
    def _provides(cls):
        return "fire"

    @abstractmethod
    def _get_fires(self):
        pass

    @final
    def get_fires(self):
        return self.check_columns(self._get_fires())


class SourceModel(Source):
    def __init__(self, bounds) -> None:
        super().__init__(bounds)

    @classmethod
    @property
    def _provides(cls):
        return "model"

    @abstractmethod
    def _get_wx_model(self, lat, lon):
        pass

    @final
    def get_wx_model(self, lat, lon):
        return self.check_columns(self._get_wx_model(lat, lon))


class SourceHourly(Source):
    def __init__(self, bounds) -> None:
        super().__init__(bounds)

    @classmethod
    @property
    def _provides(cls):
        return "hourly"

    @abstractmethod
    def _get_wx_hourly(self, lat, lon, datetime_start, datetime_end=None):
        pass

    @final
    def get_wx_hourly(self, lat, lon, datetime_start, datetime_end=None):
        return self.check_columns(self._get_wx_hourly(lat, lon, datetime_start, datetime_end))


class SourceFwi(Source):
    def __init__(self, bounds) -> None:
        super().__init__(bounds)

    @classmethod
    @property
    def _provides(cls):
        return "fwi"

    @abstractmethod
    def _get_fwi(self, lat, lon, date):
        pass

    @final
    def get_fwi(self, lat, lon, date):
        return self.check_columns(self._get_fwi(lat, lon, date))


class SourceFireWeather(Source):
    def __init__(self, bounds) -> None:
        super().__init__(bounds)

    @classmethod
    @property
    def _provides(cls):
        return "fire_weather"

    @abstractmethod
    def _get_fire_weather(self, lat, lon, date):
        pass

    @final
    def get_fire_weather(self, lat, lon, date):
        return self.check_columns(self._get_fire_weather(lat, lon, date))
