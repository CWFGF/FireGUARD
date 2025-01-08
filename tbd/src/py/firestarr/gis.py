"""Non-ArcGIS GIS utility code"""

import collections
import math
import os
import re
import shutil
import sys

import fiona.drvsupport
import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from common import (
    CREATION_OPTIONS,
    DIR_DOWNLOAD,
    DIR_EXTRACTED,
    DIR_RASTER,
    DIR_TMP,
    do_nothing,
    ensure_dir,
    ensure_string_list,
    force_remove,
    is_empty,
    listdir_sorted,
    locks_for,
    logging,
    unzip,
)
from multiprocess import Lock
from net import try_save_http
from osgeo import gdal, ogr, osr
from redundancy import call_safe, get_stack, should_ignore, try_call_safe
from tqdm_util import keep_trying, pmap

KM_TO_M = 1000
HA_TO_MSQ = 10000

CRS_LAMBERT_STATSCAN = 3347
CRS_WGS84 = 4326
CRS_LAMBERT_ATLAS = 3978
CRS_COMPARISON = CRS_LAMBERT_ATLAS
CRS_NAD83 = 4269
CRS_SIMINPUT = CRS_NAD83
VALID_GEOMETRY_EXTENSIONS = [f".{x}" for x in sorted(fiona.drvsupport.vector_driver_extensions().keys())]
VECTOR_FILE_EXTENSION = "gpkg"


def gdf_from_file(filename, *args, **kwargs):
    import warnings

    with warnings.catch_warnings():
        # avoid a bunch of ogr warnings
        warnings.filterwarnings("ignore", message="Several features with id = 0 have been found")
        # funnel everything through this so we can ignore file type everywhere else
        fct_read = gpd.read_parquet if filename.lower().endswith(".parquet") else gpd.read_file
        return call_safe(fct_read, filename, *args, **kwargs)


def ensure_geometry_file(path):
    """
    Derive a single geometry file from given path, downloading and/or
    extracting as necessary
    """
    # FIX: @ensures to make sure this is threadsafe
    path_orig = path
    # support specifying a remote path
    if re.match("^https?://", path):
        path = try_save_http(
            path,
            os.path.join(DIR_DOWNLOAD, os.path.basename(path)),
            True,
            do_nothing,
            do_nothing,
        )
    files = []
    # support .zip files
    if os.path.isfile(path):
        basename, ext = os.path.splitext(os.path.basename(path))
        if ".zip" == ext:
            dir_extract = os.path.join(DIR_EXTRACTED, basename)
            unzip(path, dir_extract)
            path = dir_extract
        else:
            # support specifying one specific file
            files = [path]
    # support directories (including results of unzip)
    if os.path.isdir(path):
        files = [os.path.join(path, x) for x in listdir_sorted(path)]
    files_features = [x for x in files if os.path.splitext(x)[1].lower() in VALID_GEOMETRY_EXTENSIONS]
    # HACK: use .shp if there is one
    have_shp = False
    if 1 < len(files_features):
        # TODO: verify if any other formats have duplicate extensions associated
        # generate list of .shp before removing from it so should be fine
        for x in [x for x in files_features if x.endswith(".shp")]:
            have_shp = True
            # if shapefile then .dbf of same name would go with it
            files_features.remove(x.replace(".shp", ".dbf"))
    if have_shp:
        files_features = [x for x in files_features if x.endswith(".shp")]
    if 1 != len(files_features):
        raise RuntimeError(f"Unable to derive valid feature file for {path_orig}")
    file = files_features[0]
    if not os.path.isfile(file):
        raise RuntimeError(f"Missing expected file: {file}")
    return file


def load_geometry_file(path):
    return gdf_from_file(ensure_geometry_file(path))


def GetFeatureCount(shp):
    """!`
    Count number of features in a shapefile
    @param shp Shapefile to count features from
    @return Number of features in shapefile, or -1 on failure
    """
    lyr = ogr.Open(shp)
    if lyr:
        return lyr.GetLayer(0).GetFeatureCount()
    return -1


def FromEPSG(epsg):
    """!
    Load spatial reference from epsg value
    @param epsg Code for spatial reference to load
    @return Spatial reference for given code
    """
    spatialReference = osr.SpatialReference()
    spatialReference.ImportFromEPSG(epsg)
    return spatialReference


def Delete(shp):
    """!
    Delete the given shapefile
    @param shp Shapefile to delete
    @return None
    """
    if os.path.exists(shp):
        ogr.GetDriverByName("ESRI Shapefile").DeleteDataSource(shp)


def GetSpatialReference(src):
    """!
    Determine spatial reference from a source file
    @param src Source file to determine spatial reference of
    @return Spatial reference of source file
    """
    if src.endswith(".shp"):
        inDataSet = ogr.GetDriverByName("ESRI Shapefile").Open(src)
        inLayer = inDataSet.GetLayer()
        ref = inLayer.GetSpatialRef()
        del inLayer
        del inDataSet
        return ref
    inDataSet = gdal.Open(src)
    ref = inDataSet.GetProjectionRef()
    s = osr.SpatialReference()
    s.ImportFromWkt(ref)
    del ref
    del inDataSet
    return s


def Project(src, outputShapefile, outSpatialRef):
    """!
    Project to given spatial reference
    @param src File to project
    @param outputShapefile Destination file to save projection to
    @param outSpatialRef Spatial reference to project into
    @return None
    """
    df = gdf_from_file(src)
    df_out = df.to_crs(outSpatialRef.ExportToWkt())
    call_safe(df_out.to_file, outputShapefile)


class Extent(object):
    """Represents the extent of a shapefile"""

    def __init__(self, src):
        """!
        Load from src
        @param self Pointer to this
        @param src Shapefile to load extent from
        """
        shp = ogr.GetDriverByName("ESRI Shapefile").Open(src)
        extent = shp.GetLayer().GetExtent()
        # Minimum X coordinate
        self.XMin = extent[0]
        # Maximum X coordinate
        self.XMax = extent[1]
        # Center between minimum and maximum X coordinates
        self.XCenter = (self.XMax - self.XMin) / 2 + self.XMin
        # Minimum Y coordinate
        self.YMin = extent[2]
        # Maximum Y coordinate
        self.YMax = extent[3]
        # Center between minimum and maximum Y coordinates
        self.YCenter = (self.YMax - self.YMin) / 2 + self.YMin


def GetCellSize(raster):
    """!
    Determine cell size for a raster and ensure pixels are square
    @param raster Raster to get cell size from
    @return Cell size for raster (m)
    """
    r = gdal.Open(raster, gdal.GA_ReadOnly)
    gt = r.GetGeoTransform()
    pixelSizeX = gt[1]
    pixelSizeY = -gt[5]
    if pixelSizeX != pixelSizeY:
        print("Raster must have square pixels")
        sys.exit(-2)
    del r
    del gt
    return pixelSizeX


def Rasterize(file_lyr, raster, reference, datatype=gdal.GDT_Byte, creation_options=CREATION_OPTIONS):
    """!
    Convert a shapefile into a raster with the given spatial reference
    # @param shp Shapefile to convert to raster
    @param raster Raster file path to save result to
    @param reference Reference raster to use for extents and alignment
    @return None
    """

    def do_rasterize():
        # Get projection info from reference image
        ref_raster = call_safe(gdal.Open, reference, gdal.GA_ReadOnly)
        gt = ref_raster.GetGeoTransform()
        pixelSizeX = gt[1]
        pixelSizeY = -gt[5]
        if pixelSizeX != pixelSizeY:
            print("Raster must have square pixels")
            sys.exit(-2)

        gdalformat = "GTiff"
        # datatype = gdal.GDT_Byte
        # datatype = gdal.GDT_UInt16
        burnVal = 1  # value for the output image pixels

        # Open Shapefile
        feature = ogr.Open(file_lyr)
        lyr = feature.GetLayer()

        # Rasterise
        # ~ print("Rasterising shapefile...")
        # crs = osr.SpatialReference(wkt=ref_raster.GetProjectionRef())
        crs = ref_raster.GetProjectionRef()
        output = gdal.GetDriverByName(gdalformat).Create(
            raster,
            ref_raster.RasterXSize,
            ref_raster.RasterYSize,
            1,
            datatype,
            options=creation_options,
        )
        output.SetProjection(crs)
        output.SetGeoTransform(ref_raster.GetGeoTransform())
        # Write data to band 1
        band = output.GetRasterBand(1)
        band.SetNoDataValue(0)
        gdal.RasterizeLayer(output, [1], lyr, burn_values=[burnVal])
        # Close datasets
        del band
        del output
        del ref_raster
        del lyr
        del feature
        # del src_ds
        # create projection file for output
        # prj = os.path.splitext(raster)[0] + ".prj"
        # with open (prj, 'w') as file:
        #     file.write(lyr.crs.ExportToWkt())
        return raster

    return call_safe(do_rasterize)


def save_point_file(latitude, longitude, out_dir, name):
    """!
    Save a file with a single point having the given coordinates
    @param latitude Latitude to use for point
    @param longitude Longitude to use for point
    @param out_dir Directory to save shapefile to
    @param name Name of point within file, and file to save to
    @return None
    """
    gdf_to_file(to_gdf(pd.DataFrame({"lat": [latitude], "lon": [longitude]})), out_dir, name)


def sum_raster(raster, band_number=1):
    """!
    Sum the value of all cells in a raster
    @param raster Raster to sum values for
    @param band_number Number of band to sum values of
    @return Result of summing raster
    """
    src = gdal.Open(raster)
    band = src.GetRasterBand(band_number)
    nodata = band.GetNoDataValue()
    r_array = np.array(band.ReadAsArray())
    r_array[r_array == nodata] = 0.0
    result = r_array.sum()
    del r_array
    del band
    del src
    return result


# Dictionary of meridians to the rasters they are for
MERIDIANS = None


def find_raster_meridians(year=None):
    """!
    Find the meridians of input rasters for the given year
    @param year Year to find raster meridians for
    @return Dictionary of meridians to raster with each meridian
    """
    global MERIDIANS
    if MERIDIANS:
        return MERIDIANS
    raster_root = None
    for folder in ["default", str(year)]:
        dir_check = os.path.join(DIR_RASTER, folder)
        if os.path.isdir(dir_check):
            raster_root = dir_check
    if not raster_root:
        raise RuntimeError(f"Could not find raster directories in {DIR_RASTER}")
    rasters = [
        os.path.join(raster_root, x)
        for x in listdir_sorted(raster_root)
        if x[-4:].lower() == ".tif" and -1 != x.find("fuel")
    ]
    result = {}
    for r in rasters:
        raster = gdal.Open(r)
        prj = raster.GetProjection()
        srs = osr.SpatialReference(wkt=prj)
        result[srs.GetProjParm("CENTRAL_MERIDIAN")] = r
        del srs
        del prj
        del raster
    MERIDIANS = result
    if is_empty(result):
        logging.error("Error: missing rasters in directory {}".format(raster_root))
    return result


def find_best_raster(lon, year=None, only_int_zones=False):
    """!
    Find the raster with the closest meridian
    @param lon Longitude to look for closest raster for
    @param year Year to find raster for
    @return Raster with the closest meridian to the desired longitude
    """
    logging.debug("Looking for raster for longitude {}".format(lon))
    best = 9999
    m = find_raster_meridians(year)
    for i in m.keys():
        if not only_int_zones or not m[i].endswith("_5.tif"):
            if abs(best - lon) > abs(i - lon):
                best = i
    return m[best]


def project_raster(
    filename,
    output_raster=None,
    outputBounds=None,
    nodata=0,
    options=["COMPRESS=LZW", "TILED=YES"],
    crs="EPSG:4326",
    resolution=None,
    format=None,
):
    if is_invalid_tiff(filename, test_read=True):
        # NOTE: DO NOT DELETE SINCE SOMETHING ELSE COULD BE WRITING CONCURRENTLY
        # force_remove(filename)
        return None

    try:
        input_raster = call_safe(gdal.Open, filename)
    except RuntimeError as ex:
        # NOTE: DO NOT DELETE SINCE SOMETHING ELSE COULD BE WRITING CONCURRENTLY
        logging.error(f"Found invalid file {filename}")
        logging.error(get_stack(ex))
        return None

    if output_raster is None:
        output_raster = filename[:-4] + ".tif"
    logging.debug(f"Projecting {filename} to {output_raster}")

    with locks_for(output_raster):

        def do_save(_):
            force_remove(_)
            ensure_dir(os.path.dirname(_))
            warp = gdal.Warp(
                _,
                input_raster,
                dstNodata=nodata,
                options=gdal.WarpOptions(
                    dstSRS=crs,
                    format=format,
                    xRes=resolution,
                    yRes=resolution,
                    outputBounds=outputBounds,
                    creationOptions=options,
                ),
            )
            geoTransform = warp.GetGeoTransform()
            minx = geoTransform[0]
            maxy = geoTransform[3]
            maxx = minx + geoTransform[1] * warp.RasterXSize
            miny = maxy + geoTransform[5] * warp.RasterYSize
            bounds = [minx, miny, maxx, maxy]
            try:
                warp = None
            except KeyboardInterrupt as ex:
                raise ex
            except Exception as ex:
                # HACK: keep getting:
                #     Exception ignored in: <built-in function delete_Dataset>
                #     Traceback (most recent call last):
                #     File "/appl/tbd/src/py/firestarr/gis.py", line 426, in do_save
                #         warp = None
                #         ^^^^
                # if not should_ignore(ex):
                #     raise ex
                pass

            # # HACK: make sure this exists and is correct
            # test_open = gdal.Open(_)
            # # HACK: avoid warning about unused variable
            # if test_open is not None:
            #     test_open = None
            return bounds

        return call_safe(do_save, output_raster)


def save_geojson(df, path):
    dir = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    file = os.path.join(dir, f"{base}.geojson")
    try:
        # HACK: avoid "The GeoJSON driver does not overwrite existing files."
        force_remove(file)
        # HACK: geojson must be WGS84
        df_crs = df.to_crs("WGS84")
        call_safe(df_crs.to_file, file)
        return file
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.error(f"Error writing to {file}:\n\t{df}")
        logging.error(get_stack(ex))
        raise ex


def vector_path(dir, base):
    # create a file path with the right extension for the vector file format we're using
    return os.path.join(dir, f"{base}.{VECTOR_FILE_EXTENSION}")


def gdf_to_file(df, dir, base=None):
    # funnel everything through this so we can ignore file type everywhere else
    if base is None:
        base = os.path.splitext(os.path.basename(dir))[0]
        dir = os.path.dirname(dir)
    file = vector_path(dir, base)
    # FIX: lots of things apparently rely on the side effects of saving files
    #      using this and then loading them again
    # HACK: don't lock on file until we fix reentrant locks
    try:
        cols = df.columns
        df = df.reset_index()
        keys = [x for x in df.columns if x not in cols]
        for k in [x for x in df.columns if x != "geometry"]:
            v = df.dtypes[k]
            # HACK: convert any type of date into string
            if "date" in str(v).lower():
                df[k] = df[k].astype(str)
            elif v == np.int64:
                df[k] = df[k].astype(int)
        # df_index = df.set_index(keys)
        fct_save = df.to_file

        def save_gpkg(f):
            # HACK: writing gpkg to azure mount is failing a lot so move after writing
            f_tmp = f.replace("/", "_")
            df.to_file(f_tmp, driver="GPKG")
            shutil.move(f_tmp, f)
            return f

        if "parquet" == VECTOR_FILE_EXTENSION:
            fct_save = df.to_parquet
        elif "gpkg" == VECTOR_FILE_EXTENSION:
            # need to specify driver
            fct_save = save_gpkg
        call_safe(fct_save, file)
        return file
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.error(f"Error writing to {file}:\n\t{df}")
        logging.error(get_stack(ex))
        raise ex


def to_gdf(df, crs=CRS_WGS84):
    geometry = df["geometry"] if "geometry" in df else gpd.points_from_xy(df["lon"], df["lat"], crs=crs)
    return gpd.GeoDataFrame(df, crs=crs, geometry=geometry)


def make_point(lat, lon, crs=CRS_WGS84):
    # always take lat lon as WGS84 but project to requested crs
    pt = gpd.points_from_xy([lon], [lat], crs=CRS_WGS84)
    if crs != CRS_WGS84:
        pt = gpd.GeoDataFrame(geometry=pt, crs=CRS_WGS84).to_crs(crs).iloc[0].geometry
    return pt


def find_closest(df, lat, lon, crs=CRS_COMPARISON, fill_missing=False):
    if df is None:
        return df
    df["dist"] = df.to_crs(crs).distance(make_point(lat, lon, crs))
    if not fill_missing:
        # previous behaviour - expected for other functions that might already
        # have different coodinates on purpose
        return df.loc[df["dist"] == np.min(df["dist"])]
    # sort by lat/lon as well in case equidistant
    df = df.sort_values(["dist", "lat", "lon"])
    # pick closest for each time
    df_closest = df.groupby(["datetime"]).first()
    if 1 != len(np.unique(df_closest[["lat", "lon"]])):
        logging.warning("Data missing for closest station for some hours so substituted")
    df_closest.crs = df.crs
    return df_closest.to_crs(CRS_WGS84)


def area_ha(df):
    return np.round(df.to_crs(CRS_COMPARISON).area / HA_TO_MSQ, 2)


def area_ha_to_radius_m(a):
    return math.sqrt(a * HA_TO_MSQ / math.pi)


def make_empty_gdf(columns):
    return gpd.GeoDataFrame({k: [] for k in columns + ["geometry"]}, crs=CRS_WGS84)


def make_gdf_from_series(row, crs):
    """Convert Series into GeoDataFrame"""
    return to_gdf(row.to_frame().transpose(), crs)


# don't need a file lock because only this process will be affected
LOCK_GDAL_EXCEPTIONS = Lock()


def with_gdal_exceptions_off(fct, *args, **kwargs):
    with LOCK_GDAL_EXCEPTIONS:
        use_exceptions = gdal.GetUseExceptions()
        try:
            # HACK: if exceptions are on then gdal_merge throws one
            gdal.DontUseExceptions()
            return fct(*args, **kwargs)
        except Exception as ex:
            # HACK: logging trace doesn't show substitution, so try making string first
            str_error = f"Error calling {fct} with arguments:\n\t{args}\n\t{kwargs}"
            logging.error(str_error)
            raise ex
        finally:
            if use_exceptions:
                gdal.UseExceptions()


def is_invalid_tiff(path, bands=[1], test_read=False):
    def do_check():
        # HACK: all these checks for None only apply when not using exceptions?
        if not os.path.isfile(path):
            return False
        src = gdal.Open(path)
        if src is None:
            return False
        for band_number in bands:
            band = src.GetRasterBand(band_number)
            if band is None:
                return False
            nodata = band.GetNoDataValue()
            if nodata:
                # HACK: just avoid not used warning
                pass
            if test_read:
                r_array = np.array(band.ReadAsArray())
                if r_array is not None:
                    return False
                del r_array
            del band
        del src
        return True

    try:
        # HACK: do this so we can catch other i/o errors
        return try_call_safe(True, do_check)
    except KeyboardInterrupt as ex:
        raise ex
    except Exception:
        return True


def find_invalid_tiffs(paths, bands=[1], test_read=False):
    paths = ensure_string_list(paths)

    def check_path(path):
        # return path if not a valid tiff
        try:
            with locks_for(path):
                if is_invalid_tiff(path, bands=bands, test_read=False):
                    return None
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            pass
        return path

    # find list of invalid files
    results = keep_trying(check_path, paths, desc="Validating rasters")
    return [x for x in results if x is not None]
