import datetime
import os
from functools import cache

import datasources.spotwx
import numpy as np
import pandas as pd
from common import (
    DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS,
    DIR_SRC_PY_FIRSTARR,
    listdir_sorted,
    logging,
    pick_max,
    pick_max_by_column,
    to_utc,
    tqdm_util,
)
from datasources.cwfis import SourceFeatureM3, SourceFireCiffc, SourceFwiCwfis
from datasources.datatypes import (
    SourceFeature,
    SourceFire,
    SourceFwi,
    SourceHourly,
    SourceModel,
    make_template_empty,
)
from gis import (
    CRS_COMPARISON,
    CRS_WGS84,
    KM_TO_M,
    area_ha,
    area_ha_to_radius_m,
    gdf_to_file,
    to_gdf,
)

STATUS_RANK = ["OUT", "UC", "BH", "OC", "UNK"]


def wx_interpolate(df):
    date_min = df["datetime"].min()
    date_max = df["datetime"].max()
    times = pd.DataFrame(pd.date_range(date_min, date_max, freq="h").values, columns=["datetime"])
    crs = df.crs
    index_names = df.index.names
    df = df.reset_index()
    idx_geom = ["lat", "lon", "geometry"]
    gdf_geom = df[idx_geom].drop_duplicates().reset_index(drop=True)
    del df["geometry"]
    groups = []
    for i, g in df.groupby(index_names):
        g_fill = pd.merge(times, g, how="left")
        # treat rain as if it all happened at start of any gaps
        g_fill["prec"] = g_fill["prec"].fillna(0)
        g_fill = g_fill.ffill()
        g_fill[index_names] = i
        groups.append(g_fill)
    df_filled = to_gdf(pd.merge(pd.concat(groups), gdf_geom), crs)
    df_filled.set_index(index_names)
    return df_filled


def find_rank(x):
    # rank is highest if unknown value
    return STATUS_RANK.index(x) if x in STATUS_RANK else (len(STATUS_RANK) - 1)


def assign_fires(
    origin,
    df_features,
    df_fires,
    days_to_keep_unmatched=DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS,
):
    # do this to make an index column
    df_features = df_features.reset_index().to_crs(CRS_COMPARISON)
    df_fires = df_fires.reset_index().to_crs(CRS_COMPARISON)
    df_join = df_features.sjoin_nearest(df_fires, how="left", max_distance=1 * KM_TO_M)
    df_join["status_rank"] = tqdm_util.apply(df_join["status"], find_rank, desc="Ranking by status")
    df_unmatched = df_join[df_join["fire_name"].isna()][["datetime_left", "geometry"]].rename(
        columns={"datetime_left": "datetime"}
    )
    # HACK: if unmatched then ignore more readily based on age
    min_active = to_utc(origin.today - datetime.timedelta(days=days_to_keep_unmatched))
    df_unmatched = df_unmatched[df_unmatched["datetime"] >= min_active].reset_index(drop=True)
    df_join = df_join[~df_join["fire_name"].isna()]
    df_join = df_join.sort_values(["index", "status_rank", "area", "fire_name"], ascending=False)
    # should mean only one copy of each geometry, and picked by fire with highest status
    df_first = df_join.groupby("index").first()
    # doesn't have crs after groupby
    df_first.crs = df_join.crs
    # want to keep all the fires that geometries intersect circles for
    # so that we can replace all of their named entries
    df_status = df_join.loc[:].set_index(["index"])
    # assign highest status for any of overlapping fires to all fires that overlap
    df_status[["status", "status_rank"]] = df_first.loc[df_status.index][["status", "status_rank"]]
    # dissolve by fire_name but use max so highest lastdate stays
    df_dissolve = df_status.dissolve(by="fire_name", aggfunc="max").reset_index()
    df_dissolve["datetime"] = pick_max(df_dissolve["datetime_left"], df_dissolve["datetime_right"])
    # at this point we might have the same geometry for multiple fires, but that
    # just means they'll all get replaced with it and then the group dissolve
    # will take care of duplicates
    df_matched = df_dissolve[["fire_name", "datetime", "status", "geometry"]]
    df_features = df_matched.reset_index(drop=True)
    df_features["area"] = area_ha(df_features)
    df_unmatched["area"] = area_ha(df_unmatched)
    return (
        df_features.set_index(["fire_name"]).to_crs(CRS_WGS84),
        df_unmatched.to_crs(CRS_WGS84),
    )


def override_fires(df_fires, df_override):
    if df_override is not None and 0 < len(df_override):
        if df_fires.crs != df_override.crs:
            raise RuntimeError("Expected matching CRS for override_fires()")
        # override df_fires when they match
        matched = list(set(df_override.index).intersection(set(df_fires.index)))
        unmatched = list(set(df_override.index).difference(set(matched)))
        if unmatched:
            logging.warning(f"Ignoring unmatched fires:\n{df_override.loc[unmatched]}")
        if 0 < len(matched):
            # can't join if nothing matches
            df_fires = df_fires.loc[:]
            df_override = df_override.loc[:]
            cols_missing = [x for x in df_override.columns if np.all(df_override[x].isna())]
            if cols_missing:
                df_override.loc[matched, cols_missing] = df_fires.loc[matched, cols_missing]
            df_fires.loc[matched] = df_override.loc[matched]
            df_fires.loc[matched, "datetime"] = pick_max_by_column(df_fires, df_override, "datetime", matched)
    return df_fires


def find_sources_in_module(module, class_type):
    import importlib
    import inspect

    module = importlib.import_module(module)
    classes = [y for y in [getattr(module, x) for x in dir(module)] if inspect.isclass(y)]
    return [c for c in classes if (issubclass(c, class_type) and not inspect.isabstract(c))]


def find_sources_in_dir(class_type, dir_search="private"):
    path = os.path.join(DIR_SRC_PY_FIRSTARR, "datasources", dir_search)
    if not os.path.isdir(path):
        return []
    files = [f.replace(".py", "") for f in listdir_sorted(path) if f.endswith(".py")]
    modules = [f"datasources.{dir_search.replace('/', '.')}.{f}" for f in files]
    from itertools import chain

    return list(chain.from_iterable([find_sources_in_module(m, class_type) for m in modules]))


def find_sources(class_type, private_first=False):
    private = find_sources_in_dir(class_type, "private")
    public = find_sources_in_dir(class_type, "public")
    # some sources
    return private + public if private_first else public + private


class SourceFireActive(SourceFire):
    def __init__(
        self,
        dir_out,
        origin,
        status_include=None,
        status_omit=["OUT"],
    ) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._origin = origin
        self._status_include = status_include
        self._status_omit = status_omit
        self._source_ciffc = SourceFireCiffc(dir_out, status_ignore=None, year=self._origin.today.year)
        # sources for features that we don't have a fire attached to
        self._source_features = [
            SourceFeatureM3(self._dir_out, self._origin),
        ] + [
            # want private sources last so they override public ones
            s(self._dir_out)
            for s in find_sources(SourceFeature, private_first=False)
        ]
        # sources for features that area associated with specific fires
        self._source_fires = [s(self._dir_out) for s in find_sources(SourceFire, private_first=False)]

    @cache
    def _get_fires(self):
        def save_fires(df, file_root):
            df_points = df[df.geometry.type == "Point"]
            df_polygons = df[df.geometry.type != "Point"]
            if 0 < len(df_points):
                gdf_to_file(
                    df_points,
                    self._dir_out,
                    f"{file_root}_points",
                )
            if 0 < len(df_polygons):
                gdf_to_file(
                    df_polygons,
                    self._dir_out,
                    f"{file_root}_polygons",
                )

        df_ciffc = self._source_ciffc.get_fires()
        df_fires = df_ciffc.loc[:]
        gdf_to_file(df_fires, self._dir_out, "df_fires_ciffc")
        df_circles = df_fires.loc[df_fires.geometry.type == "Point"].to_crs(CRS_COMPARISON)
        # HACK: put in circles of proper area so spatial join should hopefully
        # overlap actual polygons
        df_circles["geometry"] = tqdm_util.apply(
            df_circles,
            lambda x: x.geometry.buffer(max(0.1, area_ha_to_radius_m(max(0, x["area"])))),
            desc="Converting points with area to circles",
        ).simplify(100)
        df_circles = df_circles.to_crs(CRS_WGS84)
        gdf_to_file(df_circles, self._dir_out, "df_fires_circles")
        df_fires = self.check_columns(df_circles.iloc[:])
        df_unmatched = None
        # override with each source in the order they appear
        for i, src in enumerate(self._source_features):
            df_src = src.get_features()
            if 0 < len(df_src):
                save_fires(df_src, f"df_fires_from_feature_source_{i:02d}")
                df_src_fires, df_unmatched_cur = assign_fires(self._origin, df_src, df_fires)
                save_fires(df_src_fires, f"df_fires_assigned_feature_source_{i:02d}")
                save_fires(df_unmatched_cur, f"df_fires_umatched_feature_source_{i:02d}")
                df_unmatched = pd.concat([df_unmatched, df_unmatched_cur])
                df_fires = override_fires(df_fires, df_src_fires)
            save_fires(df_fires, f"df_fires_after_feature_source_{i:02d}")
        for i, src in enumerate(self._source_fires):
            df_src_fires = src.get_fires()
            save_fires(df_src, f"df_fires_from_fire_source_{i:02d}")
            df_fires = override_fires(df_fires, df_src_fires)
            save_fires(df_fires, f"df_fires_after_fire_source_{i:02d}")
        df_fires = df_fires.reset_index()
        logging.info(
            "Have %d polygons that are not tied to a fire",
            len(df_unmatched),
        )
        if self._status_include:
            df_fires = df_fires.loc[df_fires.status.isin(self._status_include)]
            logging.info(
                "Have %d features that are tied to %s fires",
                len(df_fires),
                self._status_include,
            )
        save_fires(df_fires, "df_fires_after_status_include")
        if self._status_omit:
            df_fires = df_fires.loc[~df_fires.status.isin(self._status_omit)]
            logging.info(
                "Have %d features that aren't tied to %s fires",
                len(df_fires),
                self._status_omit,
            )
        save_fires(df_fires, "df_fires_after_status_omit")
        # pretty sure U is unknown status
        df_unmatched["status"] = "U"
        df_unmatched["fire_name"] = [f"UNMATCHED_{x}" for x in df_unmatched.index]
        df_all = pd.concat([df_fires, df_unmatched])
        save_fires(df_fires, "df_fires_after_concat")
        return df_all


class SourceFwiBest(SourceFwi):
    def __init__(
        self,
        dir_out,
    ) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        # want private sources first since it stops at first match
        self._sources = [s(self._dir_out) for s in find_sources(SourceFwi, private_first=True)] + [
            SourceFwiCwfis(self._dir_out)
        ]

    @cache
    def _get_fwi(self, lat, lon, date):
        # find first fwi source that applies to this
        for src in self._sources:
            if src.applies_to(lat, lon):
                break
        return src._get_fwi(lat, lon, date)


class SourceModelAll(SourceModel):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._sources = [datasources.spotwx.SourceGEPS(self._dir_out)] + [
            # order doesn't matter since everything gets used
            s(self._dir_out)
            for s in find_sources(SourceModel)
        ]

    def _get_wx_model(self, lat, lon):
        return pd.concat([src._get_wx_model(lat, lon) for src in self._sources if src.applies_to(lat, lon)])


class SourceHourlyEmpty(SourceHourly):
    def __init__(self) -> None:
        super().__init__(bounds=None)

    def _get_wx_hourly(self, lat, lon, datetime_start, datetime_end=None):
        return make_template_empty("hourly")


class SourceHourlyBest(SourceHourly):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._sources = [
            # want private sources first since it stops at first match
            s(self._dir_out)
            for s in find_sources(SourceHourly, private_first=True)
        ] + [
            # need some default hourly weather source
            SourceHourlyEmpty()
        ]

    @cache
    def _get_wx_hourly(self, lat, lon, datetime_start, datetime_end=None):
        # find first fwi source that applies to this
        for src in self._sources:
            if src.applies_to(lat, lon):
                break
        return src._get_wx_hourly(lat, lon, datetime_start, datetime_end)
