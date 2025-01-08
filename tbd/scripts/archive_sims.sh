#!/bin/bash
KEEP_UNARCHIVED=10

# NOTE: this merges sims and runs directories for this run into root of archive
DIR_FROM_SIMS="/appl/data/sims"
DIR_FROM_RUNS="/appl/data/runs"
DIR_BKUP="/appl/data/sims.bkup"
DIR_TMP="${TMPDIR}/bkup"
SUBDIR_COMMON="current"

# override KEEP_UNARCHIVED if set in config
. /appl/data/config || . /appl/config
echo "Keeping ${KEEP_UNARCHIVED} runs unarchived"

# ensure 7za exists
7za > /dev/null || (echo "7za not found" && exit -1)

function do_archive()
{
  run="$1"
  do_delete="$2"
  # # update without existing file is the same as 'a'
  # zip_type="u"
  # '-sdel' doesn't work with 'u'
  zip_type="a"
  # always -sdel since archiving from tmp folder
  options="-mtm -mtc -mx=9 -stl -sdel"
  file_out="${DIR_BKUP}/${run}.7z"
  dir_sims="${DIR_FROM_SIMS}/${run}"
  dir_runs="${DIR_FROM_RUNS}/${run}"
  dir_tmp="${DIR_TMP}/${run}"
  mkdir -p "${DIR_TMP}"
  echo "Archiving ${run} as ${file_out}"
  # if the folders still exist then don't try to figure out what files are newer
  if [ -f "${file_out}" ]; then
    echo "Updating ${file_out}"
    echo "Checking existing archive ${file_out}"
    # if 7z can't open the archive then we need to get rid of it
    7za t "${file_out}" || (echo "Removing invalid file ${file_out}" && rm "${file_out}")
  fi
  # HACK: merge directories before zipping
  if [ "" != "${do_delete}" ]; then
    echo "Archiving and deleting ${run}"
    # sims is the bigger folder so move it
    # NOTE: this is on azure so really slow
    # if the folder was backed up previously and is still in there then mv doesn't work
    if [ -d "${dir_tmp}" ]; then
      rsync -avHP ${dir_sims}/ ${dir_tmp}
    else
      mv -v ${dir_sims} ${dir_tmp}
    fi
    # dir_runs copied below and deleted at end
  else
    echo "Archiving without deleting ${run}"
    # don't want to break things if this fails, so don't just move for now
    rsync -avHP ${dir_sims}/ ${dir_tmp}
  fi
  rsync -avHP ${dir_runs}/ ${dir_tmp}

  echo "Creating ${file_out}"
  7za ${zip_type} ${options} "${file_out}" "${dir_tmp}/*" \
      && rmdir "${dir_tmp}"
  RESULT=$?
  if [ 0 -ne "${RESULT}" ]; then
    echo "Failed to archive ${run}"
  else
    if [ "" != "${do_delete}" ]; then
      echo "Removing original folders" \
        && rm -rf ${dir_runs} \
        && rm -rf ${dir_sims}
    fi
  fi
}

pushd ${DIR_FROM_RUNS}
# get rid of bkup folder in case old junk is in there
# rm -rf ${DIR_BKUP} && \
mkdir -p ${DIR_BKUP}
rmdir * > /dev/null 2>&1
set -e
match_last=`ls -1 | grep -v "${SUBDIR_COMMON}" | tail -n1 | sed "s/.*\([0-9]\{8\}\)[0-9]\{4\}/\1/"`
# also filter out anything for today since might be symlinking to it
for run in `ls -1  | grep -v "${SUBDIR_COMMON}" | grep -v "${match_last}" | head -n-${KEEP_UNARCHIVED}`
do
  echo "${run}"
  do_archive "${run}" 1
done

# do for everything after doing things that can be deleted
for run in `ls -1 | grep -v "${SUBDIR_COMMON}"`
do
  do_archive "${run}"
done

popd
