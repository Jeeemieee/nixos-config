# The first program of every queued job, inside the job's sandbox: queue-job <folder> <log or ""> -- <command...>
# It enters the folder the job was queued from and keeps a copy of what the job prints in the worker's scratch area
folder=$1
log=$2
shift 3
# The job's sandbox has the worker's view: a folder that is not in it is refused, never replaced by another
cd "$folder" 2> /dev/null || {
  echo "queue: the folder $folder does not exist in this worker's view; nothing was run" >&2
  exit 2
}
# A sandbox without a scratch area keeps no copy
if [ -z "$log" ]; then exec "$@"; fi
mkdir -p "$(dirname "$log")"
# Whether the folder has changes that are not committed, for the run's record: the worker's own word, asked here in its own view
if git rev-parse --git-dir > /dev/null 2>&1; then
  if [ -n "$(git status --porcelain 2> /dev/null | head -n 1)" ]; then echo yes; else echo no; fi > "$(dirname "$log")/uncommitted"
fi
# Output and errors stay two streams for whoever started the job; each has its own copy step, and the kept file holds both
exec 3> >(exec tee -a "$log")
outputCopy=$!
exec 4> >(exec tee -a "$log" >&2)
errorCopy=$!
status=0
"$@" >&3 2>&4 || status=$?
exec 3>&- 4>&-
# The job ends with its command: whatever else still runs in this sandbox is stopped now, also what was started meanwhile. Only
# the two copy steps are left. With every writer gone their pipes close; they pass on what is still under way, however slowly
# it is read, and end by themselves
found=1
while [ "$found" = 1 ]; do
  found=0
  for entry in /proc/[0-9]*; do
    pid=${entry#/proc/}
    # (1 is the sandbox's own first process)
    case "$pid" in 1 | "$$" | "$outputCopy" | "$errorCopy") continue ;; esac
    # One that has ended already and only waits to be collected is no writer any more
    read -r state 2> /dev/null < "$entry/stat" || continue
    state=${state##*) }
    if [ "${state%% *}" = Z ]; then continue; fi
    kill -KILL "$pid" 2> /dev/null || true
    found=1
  done
done
wait "$outputCopy" "$errorCopy" || true
exit "$status"
