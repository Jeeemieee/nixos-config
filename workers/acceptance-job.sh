# The first program of an acceptance run, inside the job's sandbox (see docs/WORKERS.md):
#   acceptance-job <the project's .git> <the project's commit of the tests> <the worker's copy> <the copy's reference>
#                  <that reference's commit> <number of test paths> <test paths...> <command...>
# The worker starts the run and chooses nothing of it: the broker gives these arguments from the approval and from the project's
# own workers.toml. What is tested is the worker's code as it is committed on its own branch, the branch that its reviewers and
# the manager take, with the project's tests in place of the worker's; where the copy's files stand at the moment plays no part
projectGit=$1
testsCommit=$2
copy=$3
reference=$4
commit=$5
count=$6
shift 6
paths=("${@:1:count}")
shift "$count"
# In the job's own /tmp, which the agent's sandbox does not share: nothing but this job reaches the tree while the tests run
tree=$(mktemp -d /tmp/acceptance.XXXXXX)
# The worker's copy is only a remote here, as everywhere in the tools: its commit is fetched into a repository of this job's own,
# and the tree is made from that. The copy's settings are the worker's and in no commit; git run inside the copy would obey
# them, a filter that rewrites a file or an object put in another's place, and the tests would run on other code than the commit's
history=$(mktemp -d /tmp/acceptance-history.XXXXXX)
git init --quiet --bare "$history"
git --git-dir "$history" fetch --quiet --no-tags "file://$copy" "$reference" || {
  echo "acceptance: the copy's commit could not be fetched; nothing was tested" >&2
  exit 2
}
[ "$(git --git-dir "$history" rev-parse FETCH_HEAD)" = "$commit" ] || {
  echo "acceptance: ${reference#refs/heads/} of the copy is no longer at $commit, the commit this run was recorded for; nothing was tested" >&2
  exit 2
}
git --git-dir "$history" archive --format=tar "$commit" | tar -x -C "$tree" || {
  echo "acceptance: the copy's commit $commit could not be unpacked; nothing was tested" >&2
  exit 2
}
# The project's own tests, from the project's history, which the worker can only read. With no paths (the whole suite in a
# manager's copy) the tree's own tests are the ones that run
if [ "$count" -gt 0 ]; then
  for path in "${paths[@]}"; do
    # Name the absent path, not just the failed archive of the whole test list
    git --git-dir "$projectGit" cat-file -e "$testsCommit:$path" 2> /dev/null || {
      echo "acceptance: test path '$path' does not exist in the project's commit $testsCommit; every workers.toml path must exist there; nothing was tested" >&2
      exit 2
    }
    rm -rf -- "${tree:?}/$path"
  done
  git --git-dir "$projectGit" archive --format=tar "$testsCommit" -- "${paths[@]}" | tar -x -C "$tree" || {
    echo "acceptance: the project's tests (${paths[*]}) could not be taken from its history at $testsCommit; nothing was tested" >&2
    exit 2
  }
fi
cd "$tree"
exec "$@"
