# Runs inside a worker's sandbox before the agent, in the worker's folder:
#   prepare-copy <role> <project> <branch> <name> [--reviewed <an implementer's copy>]... [<manager's copy>...]
# It makes the worker's own copy of the project at the first start, and names the managers' copies as remotes to fetch from
# git runs here, inside the sandbox, because the copy is the worker's to change: nothing outside a sandbox ever runs git in it
# A reviewer's copy is a clean one, brought up to date at every start: other workers' copies are only fetched from, which runs nothing
# of theirs, and only this step sees them
role=$1
project=$2
branch=$3
name=$4
shift 4
reviewed=()
while [ "${1:-}" = --reviewed ]; do
  reviewed+=("$2")
  shift 2
done
if [ ! -e repo/.git ]; then
  case "$role" in
    implementer)
      # One branch, with copied history: hard-linked history would be the project's own files. The worker commits on a branch of its own
      git clone --quiet --no-hardlinks --single-branch --branch "$branch" "$project" repo
      git -C repo checkout --quiet -b "worker/$branch/$name"
      # The form for its intent, which the user approves before the copy becomes writable (INTENT_TEMPLATE: from the system configuration)
      if [ ! -e reports/intent.md ] && [ ! -L reports/intent.md ]; then install -m 644 "$INTENT_TEMPLATE" reports/intent.md; fi
      ;;
    manager)
      # Every branch: the manager merges between them
      git clone --quiet --no-hardlinks "$project" repo
      ;;
    reviewer | deep-reviewer)
      # Every branch of the project, to compare with; which files it shows is decided below
      git clone --quiet --no-hardlinks --no-checkout "$project" repo
      ;;
    *)
      echo "prepare-copy: the role $role has no copy of the project" >&2
      exit 2
      ;;
  esac
fi
# What a manager merged or published is fetched from its copy: `git fetch manager`
remotes=()
for copy in "$@"; do
  manager=$(basename "$(dirname "$copy")")
  if [ "$manager" = manager ]; then remote=manager; else remote=manager-$manager; fi
  remotes+=("$remote")
  if ! git -C repo remote get-url "$remote" > /dev/null 2>&1; then
    # A copy whose own git folder is damaged still starts: it is the worker's to repair
    git -C repo remote add "$remote" "$copy" || echo "prepare-copy: the remote '$remote' could not be added to this copy" >&2
  fi
done
case "$role" in
  reviewer | deep-reviewer)
    # The reviewer cannot fetch later: its copy is read-only for it. Everything is fetched here, at every start
    git -C repo fetch --quiet --prune origin
    for remote in "${remotes[@]}"; do
      git -C repo fetch --quiet --prune "$remote" || echo "prepare-copy: nothing could be fetched from the manager's copy '$remote'" >&2
    done
    # An implementer's branches are refs/reviewed/<its name>/..., for example reviewed/<its name>/worker/<branch>/<its name>
    for copy in "${reviewed[@]}"; do
      implementer=$(basename "$(dirname "$copy")")
      git -C repo fetch --quiet --no-tags --prune "file://$copy" "+refs/heads/*:refs/reviewed/$implementer/*"
    done
    if [ "$role" = reviewer ]; then
      [ "${#reviewed[@]}" = 1 ] || {
        echo "prepare-copy: a reviewer has exactly one implementer's copy to review" >&2
        exit 2
      }
      # The files of the one implementer's own branch, as it committed them
      implementer=$(basename "$(dirname "${reviewed[0]}")")
      shown=refs/reviewed/$implementer/worker/$branch/$implementer
      git -C repo rev-parse --verify --quiet "$shown^{commit}" > /dev/null || {
        echo "prepare-copy: the copy of $implementer has no branch worker/$branch/$implementer, so there is nothing to review" >&2
        exit 2
      }
    else
      # The files of the project's branch; every implementer's work is beside it as refs/reviewed/<its name>/...
      shown=refs/remotes/origin/$branch
    fi
    git -C repo checkout --quiet --force --detach "$shown"
    ;;
esac
