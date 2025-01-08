import os

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import tqdm_util
from common import DEFAULT_GROUP_DISTANCE_KM, logging
from gis import (
    CRS_COMPARISON,
    CRS_SIMINPUT,
    KM_TO_M,
    GetSpatialReference,
    find_raster_meridians,
    gdf_from_file,
)


def separate_points(f):
    pts = [x for x in f if x.geom_type == "Point"]
    polys = [x for x in f if x.geom_type != "Point"]
    return pts, polys


def group_fires_by_buffer(df_fires, group_distance_km=DEFAULT_GROUP_DISTANCE_KM):
    df_fires = df_fires.to_crs(CRS_COMPARISON)
    # buffer half distance because buffers will just touch at the original distance
    group_distance = group_distance_km * KM_TO_M / 2
    crs = df_fires.crs

    def to_gdf(d):
        return gpd.GeoDataFrame(geometry=d, crs=crs)

    groups = to_gdf(df_fires["geometry"])
    pts, polys = separate_points(groups.geometry)
    df_polys = to_gdf(polys)
    # instead of comparing distance between everything just buffer, merge, and select
    df_simplify = to_gdf(df_polys.simplify(100))
    df_buffer = to_gdf(df_simplify.buffer(group_distance))
    df_dissolve = df_buffer.dissolve()
    df_explode = df_dissolve.explode(index_parts=False)
    df_groups = None
    for i in tqdm_util.apply(range(len(df_explode)), desc="Grouping fires"):
        a = df_explode.iloc[i].geometry
        g = df_polys.loc[df_polys.intersects(a)]
        df_polys = df_polys.loc[~df_polys.intersects(a)]
        df_groups = pd.concat([df_groups, g.dissolve()])
    return df_groups


def group_fires_by_distance(df_fires, group_distance_km=DEFAULT_GROUP_DISTANCE_KM):
    df_fires = df_fires.to_crs(CRS_COMPARISON)
    group_distance = group_distance_km * KM_TO_M
    crs = df_fires.crs

    def to_gdf(d):
        return gpd.GeoDataFrame(geometry=d, crs=crs)

    groups = to_gdf(df_fires["geometry"])
    pts, polys = separate_points(groups.geometry)
    df_polys = to_gdf(polys)
    # we can check if any points are within polygons, and throw out any that are
    pts_keep = [p for p in pts if not np.any(df_polys.contains(p))]
    # p_check = [to_gdf([x]) for x in (pts_keep + polys)]
    p_check = to_gdf(pts_keep + polys)
    p = p_check.iloc[:1]
    p_check = p_check.iloc[1:]
    # just check polygon proximity to start
    # logging.info("Grouping polygons")
    with tqdm_util.apply(desc="Grouping fires", total=len(p_check)) as tq:
        p_done = []
        while 0 < len(p_check):
            n_prev = len(p_check)
            compare_to = to_gdf(p_check.geometry)
            # distances should be in meters
            compare_to["dist"] = tqdm_util.apply(
                compare_to,
                lambda x: min(x["geometry"].distance(y) for y in p.geometry),
                axis=1,
                desc="Calculating distances",
            )
            p_nearby = compare_to[compare_to.dist <= group_distance]
            if 0 < len(p_nearby):
                group = list(p.geometry) + list(p_nearby.geometry)
                g_pts, g_polys = separate_points(group)
                g_dissolve = list(to_gdf(g_polys).dissolve().geometry)
                p = to_gdf(g_pts + g_dissolve)
                # need to check whatever was far away
                p_check = compare_to[compare_to.dist > group_distance][["geometry"]]
            else:
                # nothing close to this, so done with it
                p_done.append(p)
                p = p_check.iloc[:1]
                p_check = p_check.iloc[1:]
            tq.update(n_prev - len(p_check))
    tq.update(1)
    merged = [p] + p_done
    return pd.concat(merged)


def name_groups(df):
    if df is None:
        return df
    zone_rasters = find_raster_meridians()
    zone_rasters = {k: v for k, v in zone_rasters.items() if not v.endswith("_5.tif")}

    def find_best_zone_raster(lon):
        best = 9999
        for i in zone_rasters.keys():
            if abs(best - lon) > abs(i - lon):
                best = i
        return zone_rasters[best]

    df_groups = df.loc[:]
    # HACK: can't just convert to lat/long crs and use centroids from that
    # because it causes a warning
    centroids = df_groups.centroid.to_crs(CRS_SIMINPUT)
    df_groups["lon"] = centroids.x
    df_groups["lat"] = centroids.y
    # HACK: name based on UTM coordinates
    df_groups["raster"] = tqdm_util.apply(df_groups["lon"], find_best_zone_raster, desc="Finding zone rasters")
    df_rasters = pd.DataFrame({"raster": np.unique(df_groups[["raster"]])})
    df_rasters["wkt"] = tqdm_util.apply(
        df_rasters["raster"],
        lambda r: GetSpatialReference(r).ExportToWkt(),
        desc="Finding zone wkt",
    )
    df_rasters["zone"] = tqdm_util.apply(
        df_rasters["raster"],
        lambda r: int(os.path.basename(r).split("_")[1]),
        desc="Finding zone numbers",
    )
    df_groups = pd.merge(df_groups, df_rasters)
    df_centroids = df_groups.loc[:]
    df_centroids["geometry"] = df_centroids.centroid

    def find_zone_basemap(zone, lat, centroid_utm):
        BM_MULT = 10000
        easting = int((centroid_utm.x) // BM_MULT)
        northing = int((centroid_utm.y) // BM_MULT)
        basemap = easting * 1000 + northing
        n_or_s = "N" if lat >= 0 else "S"
        return f"{zone:02d}{n_or_s}_{basemap:05d}"

    for i, g in tqdm_util.apply(df_centroids.groupby(["zone"]), desc="Naming groups by zone"):
        wkt = g["wkt"].iloc[0]
        g_zone = g.to_crs(wkt)
        df_groups.loc[g_zone.index, "fire_name"] = tqdm_util.apply(
            g_zone,
            lambda x: find_zone_basemap(x["zone"], x["lat"], x["geometry"]),
            desc="Naming groups",
        )
    # it should be impossible for 2 groups to be in the same basemap
    # because they are grouped within > 10km
    logging.info("Created %d groups", len(df))
    return df_groups


def group_fires(df_fires, group_distance_km=DEFAULT_GROUP_DISTANCE_KM):
    df_groups = group_fires_by_buffer(df_fires, group_distance_km)
    return name_groups(df_groups)


def get_fires_folder(dir_fires, crs=CRS_COMPARISON):
    proj = pyproj.CRS(crs)
    df_fires = None
    for root, dirs, files in os.walk(dir_fires):
        for f in [x for x in files if x.lower().endswith(".shp")]:
            file_shp = os.path.join(root, f)
            df_fire = gdf_from_file(file_shp).to_crs(proj)
            df_fires = pd.concat([df_fires, df_fire])
    df_fires["fire_name"] = df_fires["FIRENUMB"]
    return df_fires
