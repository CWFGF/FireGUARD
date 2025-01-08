#/bin/bash
DIR=`dirname $(realpath "$0")`
. /appl/data/config || . /appl/config

if [ -z "${GEOSERVER_LAYER}" ] \
    || [ -z "${GEOSERVER_COVERAGE}" ] \
    || [ -z "${GEOSERVER_CREDENTIALS}" ] \
    || [ -z "${GEOSERVER_SERVER}" ] \
    || [ -z "${GEOSERVER_WORKSPACE_NAME}" ] \
    || [ -z "${GEOSERVER_DIR_DATA}" ] \
    ; then
    echo Missing required configuration so not publishing
else
    GEOSERVER_EXTENSION=imagemosaic
    GEOSERVER_WORKSPACE=${GEOSERVER_SERVER}/workspaces/${GEOSERVER_WORKSPACE_NAME}
    GEOSERVER_STORE=${GEOSERVER_WORKSPACE}/coveragestores/${GEOSERVER_LAYER}
    TMP_COVERAGE=${TMPDIR}/${GEOSERVER_COVERAGE}.xml
    TAG=abstract
    echo "Publishing to ${GEOSERVER_STORE}"

    # get rid of old granules
    curl -v -v -sS -u "${GEOSERVER_CREDENTIALS}" -XDELETE "${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}/index/granules.xml"
    # update to match azure mount
    curl -v -u "${GEOSERVER_CREDENTIALS}" -XPOST -H "Content-type: text/plain" --write-out %{http_code} -d "${GEOSERVER_DIR_DATA}" "${GEOSERVER_STORE}/external.${GEOSERVER_EXTENSION}"

    # get run id from name of files
    RUN_ID=`curl -v -v -sS -u "${GEOSERVER_CREDENTIALS}" -XGET "${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}/index/granules.xml" | grep .tif | tail -n 1 | sed "s/.*firestarr_\([0-9]*\)_.*\.tif.*/\1/g"`
    ABSTRACT="FireSTARR run from ${RUN_ID}"
    # replace tag
    curl -v -v -sS -u "${GEOSERVER_CREDENTIALS}" -XGET "${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}" > ${TMP_COVERAGE}
    TAG_UPDATED="<${TAG}>${ABSTRACT}<\/${TAG}>"
    # if no tag then insert it after title
    (grep "<${TAG}>" ${TMP_COVERAGE} > /dev/null && sed -i "s/<${TAG}>[^<]*<\/${TAG}>/${TAG_UPDATED}/g" ${TMP_COVERAGE}) || sed -i "s/\( *\)\(<title>.*\)/\1\2\n\1${TAG_UPDATED}/g" ${TMP_COVERAGE}
    # upload with updated tag
    curl -v -u "${GEOSERVER_CREDENTIALS}" -XPUT -H "Content-type: text/xml" -d @${TMP_COVERAGE} "${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}"?calculate=nativebbox,latlonbbox,dimensions
    # not sure why this isn't picking up .tif band description
    sed -i "s/GRAY_INDEX/probability/g" ${TMP_COVERAGE}
    # HACK: calculate sets band name to GRAY_INDEX so set again without calculate
    curl -v -u "${GEOSERVER_CREDENTIALS}" -XPUT -H "Content-type: text/xml" -d @${TMP_COVERAGE} "${GEOSERVER_STORE}/coverages/${GEOSERVER_COVERAGE}"
fi
