#!/bin/bash
set -e

DIR=`dirname $(realpath "$0")`
pushd ${DIR}

pushd /appl/tbd
DIR_BUILD="${DIR}/build"
VARIANT=Debug
echo Set VARIANT=${VARIANT}
# rm -rf ${DIR_BUILD} \
#   &&
  /usr/bin/cmake --no-warn-unused-cli -DCMAKE_EXPORT_COMPILE_COMMANDS:BOOL=TRUE -DCMAKE_BUILD_TYPE:STRING=${VARIANT} -S/appl/tbd -B${DIR_BUILD} -G "Unix Makefiles" \
  && /usr/bin/cmake --build ${DIR_BUILD} --config ${VARIANT} --target all -j 50 --
popd

DIR_OUT="./output"
rm -rf ${DIR_OUT}

./tbd "${DIR_OUT}" \
    2023-08-03 \
    60.387 \
    -116.272 \
    01:00 \
    -i \
    --ffmc 86.0 \
    --dmc 118.4 \
    --dc 826.1 \
    --apcp_prev 0 \
    -v \
    --deterministic \
    --output_date_offsets "[1]" \
    --wx "wx.csv"

popd
