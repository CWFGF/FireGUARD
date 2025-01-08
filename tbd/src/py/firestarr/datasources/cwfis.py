import datetime
import os
from collections import Counter
from functools import cache
from urllib.error import HTTPError

import geopandas as gpd
import model_data
import pandas as pd
import tqdm_util
from common import (
    CURRENT_YEAR_ONLY,
    DEFAULT_LAST_ACTIVE_SINCE_OFFSET,
    FLAG_DEBUG,
    FMT_DATE_YMD,
    USE_CWFIS_SERVICE,
    logging,
    read_csv_safe,
    to_utc,
)
from datasources.datatypes import (
    SourceFeature,
    SourceFire,
    SourceFwi,
    make_point,
    make_template_empty,
)
from gis import CRS_COMPARISON, CRS_WGS84, KM_TO_M, gdf_from_file, gdf_to_file, to_gdf
from model_data import DEFAULT_STATUS_IGNORE, URL_CWFIS_DOWNLOADS, make_query_geoserver
from net import try_save_http

FLAG_DEBUG_PERIMETERS = False
# HACK: so we can change just the value but it also requires FLAG_DEBUG
FLAG_DEBUG_PERIMETERS = FLAG_DEBUG and FLAG_DEBUG_PERIMETERS
WFS_CIFFC = "https://geoserver.ciffc.net/geoserver/wfs?version=2.0.0"


class SourceFeatureM3Service(SourceFeature):
    def __init__(self, dir_out, last_active_since) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._last_active_since = last_active_since
        # HACK: too much data if not limited
        date_recent = to_utc(datetime.date.today() - datetime.timedelta(days=30))
        if not self._last_active_since or self._last_active_since < date_recent:
            self._last_active_since = date_recent

    @cache
    def _get_features(self):
        save_as = f"{self._dir_out}/m3_polygons.json"
        features = "lastdate,geometry"
        table_name = "public:m3_polygons"
        filter = None
        if self._last_active_since:
            # FIX: implement upper bound
            filter = f"lastdate >= {self._last_active_since.strftime('%Y-%m-%d')}T00:00:00Z"

        def do_parse(_):
            logging.debug(f"Reading {_}")
            df = gdf_from_file(_)
            df["datetime"] = to_utc(df["lastdate"])
            since = pd.to_datetime(self._last_active_since, utc=True)
            return df.loc[df["datetime"] >= since]

        return try_save_http(
            make_query_geoserver(table_name, features=features, filter=filter),
            save_as,
            False,
            None,
            do_parse,
        )


class SourceFeatureM3Download(SourceFeature):
    def __init__(self, dir_out, last_active_since) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._last_active_since = last_active_since

    @cache
    def _get_features(self):
        def get_shp(filename):
            for ext in ["dbf", "prj", "shx", "shp"]:
                url = f"{URL_CWFIS_DOWNLOADS}/hotspots/{filename}.{ext}"
                # HACK: relies on .shp being last in list
                f = try_save_http(
                    url,
                    os.path.join(self._dir_out, os.path.basename(url)),
                    keep_existing=True,
                    fct_pre_save=None,
                    fct_post_save=None,
                )
            gdf = gdf_from_file(f)
            return gdf

        df = get_shp("perimeters")
        # HACK: if empty then no results returned so fill with today where missing
        df.loc[df["LASTDATE"].isna(), "LASTDATE"] = datetime.date.today()
        df["datetime"] = to_utc(df["LASTDATE"])
        since = pd.to_datetime(self._last_active_since, utc=True)
        df = df.loc[df["datetime"] >= since]
        # HACK : add in hotspots
        df_pts = get_shp("hotspots")
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_pts, self._dir_out, "df_hotspots")
        # HACK: if empty then no results returned so fill with today where missing
        # df_pts.rename(columns={"REP_DATE": "LASTDATE"})
        # buffer around hotspots
        resolution = 100
        buffer_size = 0.1 * KM_TO_M
        logging.info("Buffering hotspots")
        df_pts.geometry = df_pts.buffer(buffer_size)
        # gdf_to_file(df_pts, self._dir_out, "df_hotspots_buffer")
        # df_pts = df_pts.dissolve().reset_index()
        # gdf_to_file(df_pts, self._dir_out, "df_hotspots_dissolve")
        logging.info("Simplifying buffer")
        df_pts.geometry = df_pts.simplify(resolution)
        # gdf_to_file(df_pts, self._dir_out, "df_hot/spots_simplify")
        logging.info("Finding times")
        df_pts.loc[:, "LASTDATE"] = datetime.date.today()
        df_pts["datetime"] = to_utc(df_pts["LASTDATE"])
        # df = df.reset_index()[["datetime", "geometry"]]
        # gdf_to_file(df, self._dir_out, "df_perimeters_basic")
        df_pts = df_pts.reset_index()[["datetime", "geometry"]]
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_pts, self._dir_out, "df_hotspots_basic")
        logging.info("Buffering perimeters")
        df_perims_buffer = df.iloc[:]
        df_perims_buffer.geometry = df_perims_buffer.buffer(1.1 * KM_TO_M, resolution=resolution)
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_pts, self._dir_out, "df_perims_buffer")
        logging.info("Finding hotspots that are too close to perimeters")
        df_join = gpd.sjoin(left_df=df_pts, right_df=df_perims_buffer, how="left")
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_join, self._dir_out, "df_join")
        logging.info("Removing hotspots that are too close to perimeters")
        df_join = df_join.loc[df_join["index_right"].isnull()]
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_join, self._dir_out, "df_join_exclude")
        logging.info("Dissolving features")
        df_join = df_join.dissolve().reset_index()
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_join, self._dir_out, "df_join_exclude_dissolve")
        logging.info("Converting multipolygons to polygons")
        df_join = df_join.explode(index_parts=False)
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_join, self._dir_out, "df_join_explode")
        logging.info("Combining remaining hotspots with existing perimeters")
        df_both = pd.concat([df, df_join])
        if FLAG_DEBUG_PERIMETERS:
            gdf_to_file(df_both, self._dir_out, "df_perimeters_hotspots")
        # df_both = df_both.reset_index()[["datetime", "geometry"]]
        # gdf_to_file(df_both, self._dir_out, "df_both_basic")
        # df_both = df_both.dissolve().reset_index()
        # gdf_to_file(df_both, self._dir_out, "df_both_dissolve")
        # exit()
        logging.info("Done creating features from M3 polygons and hotspots")
        return df_both


class SourceFeatureM3(SourceFeature):
    def __init__(self, dir_out, origin, last_active_since_offset=DEFAULT_LAST_ACTIVE_SINCE_OFFSET) -> None:
        super().__init__(bounds=None)
        self._origin = origin
        self._dir_out = dir_out
        # either use number of days or get everything for this year
        self._last_active_since = (
            self._origin.offset(-last_active_since_offset)
            if last_active_since_offset is not None
            else (datetime.date(self._origin.today.year, 1, 1)
                  if CURRENT_YEAR_ONLY else datetime.date(self._origin.today.year - 1, 1, 1))
        )
        self._source = (SourceFeatureM3Service if USE_CWFIS_SERVICE else SourceFeatureM3Download)(
            self._dir_out, self._last_active_since
        )

    def _get_features(self):
        return self._source.get_features()


def make_name_ciffc(df):
    def make_name(date, agency, fire):
        return f"{date.year}_{agency.upper()}_{fire}"

    return tqdm_util.apply(
        df,
        lambda x: make_name(x["datetime"], x["field_agency_code"], x["field_agency_fire_id"]),
        desc="Generating names",
    )


class SourceFireDipService(SourceFire):
    TABLE_NAME = "public:activefires"

    def __init__(self, dir_out, year, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_ignore = [] if status_ignore is None else status_ignore
        self._year = year

    @cache
    def _get_fires(self):
        save_as = f"{self._dir_out}/dip_current.json"

        filter = " and ".join(
            [f"\"stage_of_control\"<>'{status}'" for status in self._status_ignore]
            + [
                "agency<>'ak'",
                "agency<>'conus'",
                f"startdate during {self._year}-01-01T00:00:00Z/P1Y",
            ]
        )

        def do_parse(_):
            gdf = gdf_from_file(_)
            # only get latest status for each fire
            gdf = gdf.iloc[gdf.groupby(["firename"])["last_rep_date"].idxmax()]
            gdf = gdf.rename(
                columns={
                    "stage_of_control": "status",
                    "firename": "field_agency_fire_id",
                    "hectares": "area",
                    "last_rep_date": "datetime",
                    "agency": "field_agency_code",
                }
            )
            gdf["fire_name"] = make_name_ciffc(gdf)
            gdf = gdf.to_crs(CRS_WGS84)
            return clean_fires(gdf, self._year)

        return try_save_http(
            make_query_geoserver(self.TABLE_NAME, filter=filter, crs="EPSG:4326"),
            save_as,
            False,
            None,
            do_parse,
        )


def clean_fires(gdf, year):
    gdf["datetime"] = pd.to_datetime(gdf["datetime"], errors="coerce")
    gdf["fire_name"] = make_name_ciffc(gdf)
    # only pick current year fires
    if CURRENT_YEAR_ONLY:
        gdf = gdf.loc[gdf["datetime"].apply(lambda x: x.year) == year]
    gdf = gdf.set_index(["fire_name"])
    dupes = [k for k, v in Counter(gdf.reset_index()["fire_name"]).items() if v > 1]
    df_dupes = gdf.loc[dupes].reset_index()
    gdf = gdf.drop(dupes)
    df_dupes.sort_values(["fire_name", "datetime", "area"], ascending=False)[
        ["fire_name", "datetime", "area", "status"]
    ]
    df_pick = df_dupes.sort_values(["fire_name", "datetime", "area"], ascending=False).groupby(["fire_name"]).first()
    df_pick.crs = df_dupes.crs
    gdf = pd.concat([gdf, df_pick])
    return gdf


class SourceFireCiffcService(SourceFire):
    TABLE_NAME = "ciffc:ytd_fires"

    def __init__(self, dir_out, year, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_ignore = [] if status_ignore is None else status_ignore
        self._year = year

    @cache
    def _get_fires(self):
        save_as = f"{self._dir_out}/ciffc_current.json"
        filter = (
            " and ".join([f"\"field_stage_of_control_status\"<>'{status}'" for status in self._status_ignore]) or None
        )

        def do_parse(_):
            gdf = gdf_from_file(_)
            # HACK: ignore previous year fires
            if CURRENT_YEAR_ONLY:
                gdf = gdf.loc[gdf["field_situation_report_date"].apply(lambda x: x.year) == self._year]
            gdf = gdf.rename(
                columns={
                    "field_status_date": "datetime",
                    "field_stage_of_control_status": "status",
                    "field_fire_size": "area",
                }
            )
            return clean_fires(gdf, self._year)

        return try_save_http(
            make_query_geoserver(
                self.TABLE_NAME,
                filter=filter,
                wfs_root=WFS_CIFFC,
            ),
            save_as,
            False,
            None,
            do_parse,
        )


class SourceFireCiffc(SourceFire):
    def __init__(self, dir_out, year, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._source_ciffc = SourceFireCiffcService(dir_out, year, status_ignore)
        self._source_dip = SourceFireDipService(dir_out, year, status_ignore)

    def _get_fires(self):
        try:
            return self._source_ciffc.get_fires()
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            return self._source_dip.get_fires()


def select_fwi(lat, lon, df_wx, columns):
    if df_wx is None:
        return make_template_empty("fwi")
    if 0 < len(df_wx):
        for index in columns:
            df_wx = df_wx.loc[~df_wx[index].isna()]
        cols_float = [x for x in df_wx.columns if x not in ["datetime", "geometry"]]
        df_wx[cols_float] = df_wx[cols_float].astype(float)
        df_wx = df_wx.to_crs(CRS_COMPARISON)
        pt = make_point(lat, lon, CRS_COMPARISON)
        dists = df_wx.distance(pt)
        df_wx = df_wx.loc[dists == min(dists)]
    return df_wx


class SourceFwiCwfisDownload(SourceFwi):
    URL_STNS = f"{URL_CWFIS_DOWNLOADS}/fwi_obs/cwfis_allstn2022.csv"

    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._have_dates = {}

    @classmethod
    @cache
    def _get_stns(cls, dir_out):
        return try_save_http(
            cls.URL_STNS,
            os.path.join(dir_out, os.path.basename(cls.URL_STNS)),
            keep_existing=True,
            fct_pre_save=None,
            fct_post_save=lambda _: gdf_from_file(_)[["aes", "wmo", "lat", "lon"]],
        )

    @classmethod
    @cache
    def _get_wx_base(
        cls,
        dir_out,
        date,
    ):
        def do_parse(_):
            if _ is None:
                return None
            logging.debug("Reading {}".format(_))
            df = read_csv_safe(_, skipinitialspace=True)
            df = df.loc[df["NAME"] != "NAME"]
            df.columns = [x.lower() for x in df.columns]
            df = df.loc[~df["ffmc"].isna()]
            df["wmo"] = df["wmo"].astype(str)
            df = pd.merge(df, stns, on=["aes", "wmo"])
            df = df[["lat", "lon"] + cls.columns]
            df["datetime"] = pd.to_datetime(date) + datetime.timedelta(hours=12)
            df = df.sort_values(["datetime", "lat", "lon"])
            return to_gdf(df)

        ymd = date.strftime(FMT_DATE_YMD)
        url = f"{URL_CWFIS_DOWNLOADS}/fwi_obs/current/cwfis_fwi_{ymd}.csv"
        stns = cls._get_stns(dir_out)
        try:
            # HACK: catch 404 here so other functions don't cache values
            return try_save_http(
                url,
                os.path.join(dir_out, os.path.basename(url)),
                keep_existing=True,
                fct_pre_save=None,
                fct_post_save=do_parse,
                check_code=True,
            )
        except HTTPError as ex:
            if 404 == ex.code:
                logging.warning(ex)
                return None
            else:
                raise ex

    def _get_fwi(self, lat, lon, date):
        return select_fwi(lat, lon, self._get_wx_base(self._dir_out, date), self.columns)


class SourceFwiCwfisService(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out

    def _get_fwi(self, lat, lon, date):
        df_wx = model_data.get_wx_cwfis(self._dir_out, date, indices=",".join(self.columns))
        return select_fwi(lat, lon, df_wx, self.columns)


class SourceFwiCwfis(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._source = SourceFwiCwfisService(dir_out) if USE_CWFIS_SERVICE else SourceFwiCwfisDownload(dir_out)

    def _get_fwi(self, lat, lon, date):
        return self._source.get_fwi(lat, lon, date)
