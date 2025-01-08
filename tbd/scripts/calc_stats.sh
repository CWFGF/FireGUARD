#!/bin/bash
DIR=`dirname $(realpath "$0")`
RUN_ID=`pwd | sed "s/.*\/\(.*\)/\1/g"`
PREFIX="${TMPDIR}/${RUN_ID}"
FILE_GROUPS="${PREFIX}_files.txt"
FILE_TIMES="${PREFIX}_times.txt"
FILE_SIMS="${PREFIX}_sims.txt"
FILE_STATS="${RUN_ID}_stats.csv"
find -type f -name "firestarr.log" | sort | sed "s/.\/sims\/\([^/\]*\)\/.*/\1/g" > "${FILE_GROUPS}"
${DIR}/calc_all_times.sh > "${FILE_TIMES}"
${DIR}/calc_count_sims.sh > "${FILE_SIMS}"
echo group,seconds,simulations > "${FILE_STATS}"
paste "${FILE_GROUPS}" "${FILE_TIMES}" "${FILE_SIMS}" -d "," >> "${FILE_STATS}"
sed 1d "${FILE_STATS}" | ministat -d, -C2 -n | sed "1s/.*/Simulation Time (seconds)/; s/^x /  /g"
sed 1d "${FILE_STATS}" | ministat -d, -C3 -n | sed "1s/.*/Simulations/; s/^x /  /g"
