DIR_PERF=${TMPDIR}/perf
DIR_BUILD=./build
FILE_PERF=${DIR_PERF}/perf.data
FREQ=100
DIR_FG=/appl/FlameGraph
sudo sysctl -w kernel.perf_event_paranoid=1
[ ! -d "${DIR_PERF}" ] && mkdir -p "${DIR_PERF}"
# don't make this an actual submodule because it's just this script that needs it
[ ! -d "${DIR_FG}" ] && sudo git clone https://github.com/brendangregg/FlameGraph.git ${DIR_FG} && sudo chown -R ${USER}:${USER} ${DIR_FG}
rm -rf ${DIR_BUILD}
cmake --no-warn-unused-cli -DCMAKE_EXPORT_COMPILE_COMMANDS:BOOL=TRUE -DCMAKE_BUILD_TYPE:STRING=RelWithDebInfo -S/appl/tbd -B${DIR_BUILD} -G "Unix Makefiles"
cmake --build ${DIR_BUILD} --config Debug --target all -j $(nproc) --
cp ${DIR_BUILD}/tbd /appl/tbd/tbd
time perf record -o ${FILE_PERF} -F ${FREQ} -g --call-graph=dwarf -- $* > ${DIR_PERF}/run.log
chown ${USER}:${USER} ${FILE_PERF}
perf script -i ${FILE_PERF} | ${DIR_FG}/stackcollapse-perf.pl | ${DIR_FG}/flamegraph.pl > flame.html
