# What exists of the workers, and the user's own steps with it; runs as the user, outside every sandbox (see docs/WORKERS.md)
#   workers list                                  every worker and every ordinary session's scratch area: role, state, sizes, commits not merged
#   workers remove [--force] <project>/<branch>/<name>
#                                                 archive its records, reports and task file; its folder is then kept for some days
#                                                 and can be restored; its scratch area is destroyed. Refused while it has
#                                                 uncommitted changes or commits that no manager's copy and not the project holds
#   workers remove --merged <project>             the same for every implementer of the project that `workers list` calls removable:
#                                                 its work is merged, it reported nothing uncommitted, and it does not run. Each is
#                                                 asked the two questions again; one that fails them is left and named
#   workers restore <project>/<branch>/<name>     undo a removal while the folder is kept
#   workers remove-session <project>-<digest>     destroy the scratch area and the run records of a project's ordinary sessions
#   workers take [<manager>]                      in the project: bring what the manager prepared on the main branch of its copy
#                                                 into the project, staged and not committed, for your review and your commit
#   workers take --branch <name> [<manager>]      the same for a side branch that the manager prepared: its content is staged on
#                                                 that branch of the project, which is made if the project does not have it
#   workers status [--json]                       what every worker does and how far it is, with the origin of every value: measured,
#                                                 recorded, derived, or claimed by an agent (workers/status.py)
#   workers watch [<options>]                     the same as a live overview in the terminal; it only displays (workers-dashboard/)
#   workers approve [--without-form | --revoke] <project>/<branch>/<name>
#                                                 an implementer's copy of the project is read-only until you approve its intent:
#                                                 the form is shown, you choose an approach and type yes (workers/approve.py)
#   workers found [--with-large-files]            in a project: keep the work that is not committed, as it lies there, on a new
#                                                 branch found/<date>, and every stash on a branch beside it; nothing of the
#                                                 working tree, the index or the current branch is changed
# git never runs here in a folder an agent writes. A worker's copy is only fetched from, into a repository of the tools' own,
# and that is done in one place, the status's program (STATUS); the one question that needs git inside a copy (are there
# uncommitted changes) is asked in a sandbox that sees that copy and nothing else
# HELPER (the root helper through sudo, or empty on a machine with plain folders) and the numbers come from the system configuration
die() {
  echo "workers: $1" >&2
  exit 2
}
state=$HOME/.local/state/workers
folders=$HOME/workers
areas=$HOME/scratch/workers
validName() { [[ $1 =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$ ]]; }
read -r -a helper <<< "$HELPER"
read -r -a status <<< "$STATUS"

# <project>/<branch>/<name> into the three names, each checked
worker() {
  IFS=/ read -r project branch name rest <<< "$1"
  if [ -n "${rest:-}" ] || ! validName "${project:-}" || ! validName "${branch:-}" || ! validName "${name:-}"; then
    die "'$1' is not <project>/<branch>/<name>"
  fi
}

# Commits of a worker's copy that neither the project nor another manager's copy holds, asked now: a number, - without a copy,
# ? when they cannot be counted
unmerged() { "${status[@]}" --unmerged "$1/$2/$3" || echo "?"; }

# Whether a copy has uncommitted changes: yes, no, or ? when git cannot say. Asked inside a sandbox that holds the copy read-only
uncommitted() {
  local copy=$1 changes
  # A program planted in the copy's settings runs in there too: within the workers' memory, and for a limited time
  if changes=$(systemd-run --user --scope --quiet --collect --expand-environment=no --slice=workers-jobs.slice \
    --description="Question about uncommitted changes in $copy" -p MemoryMax="$QUESTION_MEMORY" -p MemorySwapMax=0 -p RuntimeMaxSec="$QUESTION_SECONDS" -p TimeoutStopSec=5 \
    -- bwrap --unshare-all --die-with-parent --ro-bind /nix/store /nix/store --proc /proc --dev /dev --tmpfs /tmp \
    --ro-bind "$copy" "$copy" --chdir "$copy" --clearenv -- "$(command -v git)" status --porcelain 2> /dev/null); then
    if [ -n "$changes" ]; then echo yes; else echo no; fi
  else
    echo "?"
  fi
}

running() { systemctl --user is-active --quiet "worker:$1:$2:$3.scope"; }
megabytes() { echo "$((($1 + 524288) / 1048576))M"; }

# The project this command was started in: the nearest folder upwards that holds .git. No agent writes a project, so git may run
# in it here; a worker's folder is refused, since an agent does write that
inProject() {
  project=$(pwd -P)
  while [ "$project" != / ] && [ ! -e "$project/.git" ]; do project=$(dirname "$project"); done
  [ -e "$project/.git" ] || die "this is not inside a project"
  case "$project/" in
    "$folders"/* | "$areas"/*) die "$project is a worker's folder, which an agent writes: git is not run in it here" ;;
  esac
}

# Whether a worker's folder carries the mark of a removal now; the list that is read below may be older
marked() {
  local dataset mark
  while IFS=$'\t' read -r dataset _ _ mark; do
    if [ "$dataset" = "$workersDataset/$1/$2/$3" ] && [[ $mark =~ ^[0-9]+$ ]]; then return 0; fi
  done < <("${helper[@]}" status)
  return 1
}

# Size of a folder or area: from the dataset, or measured on a machine with plain folders
declare -A used retired
if [ "${#helper[@]}" -gt 0 ]; then
  while IFS=$'\t' read -r dataset bytes _ mark; do
    used[$dataset]=$bytes
    retired[$dataset]=$mark
  done < <("${helper[@]}" status)
  workersDataset=$(findmnt -rn -o SOURCE --mountpoint "$folders")
  areasDataset=$(findmnt -rn -o SOURCE --mountpoint "$areas")
  # A removed worker whose folder the system's timer has destroyed since: the tools' records of it go too. (Only when the list
  # above is whole, which it is when it names the parent of the folders)
  if [ -n "$workersDataset" ] && [ -n "${used[$workersDataset]:-}" ]; then
    for record in "$state"/*/roles-removed/*/*; do
      [ -f "$record" ] || continue
      name=$(basename "$record")
      branch=$(basename "$(dirname "$record")")
      project=$(basename "$(dirname "$(dirname "$(dirname "$record")")")")
      if [ -z "${used[$workersDataset/$project/$branch/$name]:-}" ]; then
        rm -f "$record" "$state/$project/approvals-removed/$branch/$name" "$state/$project/starts/$branch/$name" "$state/$project/reviews/$branch"/*/"$name"
        rm -rf "$state/$project/reviews/$branch/$name"
      fi
    done
  fi
fi
size() {
  local path=$1 dataset
  if [ "${#helper[@]}" -gt 0 ]; then
    case "$path" in
      "$folders"/*) dataset=$workersDataset/${path#"$folders"/} ;;
      *) dataset=$areasDataset/${path#"$areas"/} ;;
    esac
    if [ -n "${used[$dataset]:-}" ]; then megabytes "${used[$dataset]}"; else echo -; fi
  elif [ -d "$path" ]; then
    megabytes "$(du -sb "$path" | cut -f1)"
  else
    echo -
  fi
}

action=${1:-}
case "$action" in
  approve)
    # A program of its own; APPROVE comes from the system configuration
    read -r -a approve <<< "$APPROVE"
    exec "${approve[@]}" "${@:2}"
    ;;
  status)
    # A program of its own; STATUS comes from the system configuration
    exec "${status[@]}" "${@:2}"
    ;;
  watch)
    # A program of its own, which asks the status's program for its document; WATCH comes from the system configuration
    exec "$WATCH" "${@:2}"
    ;;
  list)
    # Of every worker, its commits that nobody else holds and whether it is removable: from the status's program
    declare -A held removable
    while IFS=$'\t' read -r project branch name commits can _; do
      held[$project/$branch/$name]=$commits
      removable[$project/$branch/$name]=$can
    done < <("${status[@]}" --list)
    printf '%-14s %-12s %-18s %-13s %-22s %8s %8s %s\n' PROJECT BRANCH NAME ROLE STATE FOLDER SCRATCH UNMERGED
    for record in "$state"/*/roles/*/* "$state"/*/roles-removed/*/*; do
      [ -f "$record" ] || continue
      name=$(basename "$record")
      branch=$(basename "$(dirname "$record")")
      project=$(basename "$(dirname "$(dirname "$(dirname "$record")")")")
      case "$record" in
        */roles-removed/*)
          condition="removed"
          if [ "${#helper[@]}" -gt 0 ] && [[ ${retired[$workersDataset/$project/$branch/$name]:-} =~ ^[0-9]+$ ]]; then
            condition="removed, kept to $(date -d "@$((${retired[$workersDataset/$project/$branch/$name]} + HOLD_DAYS * 86400))" +%F)"
          fi
          commits=-
          ;;
        *)
          if running "$project" "$branch" "$name"; then
            condition=running
          elif [ "${removable[$project/$branch/$name]:-}" = yes ]; then
            condition=removable
          else
            condition=stopped
          fi
          commits=${held[$project/$branch/$name]:-?}
          ;;
      esac
      printf '%-14s %-12s %-18s %-13s %-22s %8s %8s %s\n' "$project" "$branch" "$name" "$(head -c 20 "$record")" "$condition" \
        "$(size "$folders/$project/$branch/$name")" "$(size "$areas/$project/$branch/$name")" "$commits"
    done
    # Ordinary sessions have a scratch area and no folder
    for area in "$areas"/*/plain/session; do
      [ -d "$area" ] || continue
      # With datasets, an empty folder may be left where a removed area was mounted
      if [ "${#helper[@]}" -gt 0 ] && [ -z "${used[$areasDataset/${area#"$areas"/}]:-}" ]; then continue; fi
      printf '%-14s %-12s %-18s %-13s %-22s %8s %8s %s\n' "$(basename "$(dirname "$(dirname "$area")")")" - - session - - "$(size "$area")" -
    done
    ;;
  remove)
    # --merged <project>: every implementer of the project whose work is merged, by this same action, one at a time
    if [ "${2:-}" = --merged ]; then
      target=${3:-}
      validName "$target" || die "'$target' is not a project's name, as 'workers list' shows it"
      [ -d "$state/$target/roles" ] || die "$target has no workers"
      [ "${#helper[@]}" -gt 0 ] || die "workers are plain folders on this machine: a removal that can be undone needs the datasets"
      count=0
      # Implementers first. A reviewer can become eligible because one of these removals completed
      while IFS=$'\t' read -r project branch name _ can why <&3; do
        [ "$project" = "$target" ] || continue
        [ "$(cat "$state/$project/roles/$branch/$name" 2> /dev/null)" = implementer ] || continue
        if [ "$can" = yes ]; then
          # The two questions are asked again, now: what the list says rests on the worker's last report
          if said=$("$0" remove "$project/$branch/$name" 2>&1 < /dev/null); then
            echo "$said"
            count=$((count + 1))
          else
            echo "left $project/$branch/$name: ${said#workers: }"
          fi
        elif [ "$why" != - ]; then
          echo "left $project/$branch/$name: $why"
        fi
      done 3< <("${status[@]}" --list)
      # Ask again after the implementers: remove a reviewer only when every implementer it reviewed is gone
      while IFS=$'\t' read -r project branch name _ can why <&3; do
        [ "$project" = "$target" ] || continue
        [ "$(cat "$state/$project/roles/$branch/$name" 2> /dev/null)" = reviewer ] || continue
        if [ "$can" = yes ]; then
          if said=$("$0" remove "$project/$branch/$name" 2>&1 < /dev/null); then
            echo "$said"
            count=$((count + 1))
          else
            echo "left $project/$branch/$name: ${said#workers: }"
          fi
        else
          echo "left $project/$branch/$name: $why"
        fi
      done 3< <("${status[@]}" --list)
      echo "$count worker(s) of $target removed; managers and deep reviewers are not removed by --merged (workers remove <project>/<branch>/<name>)"
      exit 0
    fi
    force=0
    if [ "${2:-}" = --force ]; then
      force=1
      shift
    fi
    worker "${2:-}"
    record=$state/$project/roles/$branch/$name
    [ -f "$record" ] || die "there is no worker $project/$branch/$name"
    running "$project" "$branch" "$name" && die "the worker $project/$branch/$name is running: end its session first"
    removed() {
      mkdir -p "$state/$project/roles-removed/$branch"
      mv "$record" "$state/$project/roles-removed/$branch/$name"
      # An implementer's approval is set aside with it: it comes back with a restore, and no later worker of this name finds it
      if [ -f "$state/$project/approvals/$branch/$name" ]; then
        mkdir -p "$state/$project/approvals-removed/$branch"
        mv "$state/$project/approvals/$branch/$name" "$state/$project/approvals-removed/$branch/$name"
      fi
      # The tools' own repository lets the copy go
      "${status[@]}" --forget "$project/$branch/$name"
    }
    # A removal that was interrupted after the folder was marked: complete it, without a second archive
    if [ "${#helper[@]}" -gt 0 ] && [[ ${retired[$workersDataset/$project/$branch/$name]:-} =~ ^[0-9]+$ ]]; then
      "${helper[@]}" retire "$project" "$branch" "$name" || die "the removal of $project/$branch/$name could not be completed"
      removed
      echo "removed $project/$branch/$name: an earlier removal was completed; the folder is kept for $HOLD_DAYS days from then (workers restore $project/$branch/$name)"
      exit 0
    fi
    copy=$folders/$project/$branch/$name/repo
    if [ -e "$copy/.git" ] || [ -L "$copy/.git" ]; then
      changes=$(uncommitted "$copy")
      commits=$(unmerged "$project" "$branch" "$name")
      if [ "$force" = 0 ]; then
        [ "$changes" = no ] || die "refusing: the copy of $project/$branch/$name has uncommitted changes, or git cannot read it ($changes); --force removes it all the same"
        [ "$commits" = 0 ] || die "refusing: the copy of $project/$branch/$name has $commits commit(s) that neither the project nor a manager's copy holds; --force removes it all the same"
      fi
    fi
    [ "${#helper[@]}" -gt 0 ] || die "workers are plain folders on this machine: a removal that can be undone needs the datasets"
    # What is kept for good: the records of its runs, its reports and its task. Links are copied as links, never followed
    archive=$folders/$project/archive/$branch-$name-$(date +%Y%m%d-%H%M%S)
    mkdir -p "$archive"
    for part in records reports; do
      if [ -d "$folders/$project/$branch/$name/$part" ]; then cp -rP "$folders/$project/$branch/$name/$part" "$archive/"; fi
    done
    if [ -e "$folders/$project/instructions/$branch/$name.md" ] || [ -L "$folders/$project/instructions/$branch/$name.md" ]; then
      cp -P "$folders/$project/instructions/$branch/$name.md" "$archive/task.md"
    fi
    # The helper changes nothing unless it can unmount both: then the worker is as it was, and so is the archive
    if ! "${helper[@]}" retire "$project" "$branch" "$name"; then
      # Only its last step, destroying the scratch area, can fail after the folder was marked: the removal then took place, and the archive stays
      if marked "$project" "$branch" "$name"; then
        die "the folder of $project/$branch/$name is unmounted and kept, and its records, reports and task are in $archive, but its scratch area could not be destroyed; run 'workers remove $project/$branch/$name' again to complete the removal"
      fi
      rm -rf "$archive"
      die "the worker $project/$branch/$name was not removed and is as it was"
    fi
    removed
    echo "removed $project/$branch/$name: records, reports and task are in $archive; the folder is kept for $HOLD_DAYS days (workers restore $project/$branch/$name)"
    ;;
  restore)
    worker "${2:-}"
    record=$state/$project/roles-removed/$branch/$name
    [ -f "$record" ] || die "there is no removed worker $project/$branch/$name"
    [ "${#helper[@]}" -gt 0 ] || die "workers are plain folders on this machine: nothing was removed"
    "${helper[@]}" restore "$project" "$branch" "$name" || die "the worker $project/$branch/$name could not be restored"
    mkdir -p "$state/$project/roles/$branch"
    mv "$record" "$state/$project/roles/$branch/$name"
    if [ -f "$state/$project/approvals-removed/$branch/$name" ]; then
      mkdir -p "$state/$project/approvals/$branch"
      mv "$state/$project/approvals-removed/$branch/$name" "$state/$project/approvals/$branch/$name"
    fi
    echo "restored $project/$branch/$name; its scratch area is made again at its next start"
    ;;
  remove-session)
    key=${2:-}
    validName "$key" || die "'$key' is not a session's name as 'workers list' shows it: <project>-<digest>"
    [ -d "$areas/$key/plain/session" ] || die "there is no ordinary session $key"
    if systemctl --user list-units --plain --no-legend "pi-$key-*.scope" | grep -q .; then die "an ordinary session of $key is running: end it first"; fi
    if [ "${#helper[@]}" -gt 0 ]; then
      "${helper[@]}" drop-area "$key" plain session || die "the scratch area of $key could not be destroyed"
    else
      rm -rf "${areas:?}/$key"
    fi
    rm -rf "$HOME/.local/state/workers-plain/$key"
    echo "removed the scratch area and the run records of the ordinary sessions of $key"
    ;;
  take)
    # --branch <name>: a side branch that the manager prepared, in place of the main branch
    side=
    if [ "${2:-}" = --branch ]; then
      side=${3:-}
      validName "$side" || die "'$side' is not a branch name that workers can have: 1 to 48 letters, digits, '.', '_' or '-'"
      case "$side" in manager | archive | instructions | plain | old) die "'$side' cannot be a branch name: the project's folder of that name is in its place" ;; esac
      shift 2
    fi
    manager=${2:-manager}
    validName "$manager" || die "'$manager' is not a manager's name"
    inProject
    name=$(basename "$project")
    [ "$(cat "$state/$name/main" 2> /dev/null)" = "$project" ] || die "$project has no workers"
    copy=$folders/$name/manager/$manager/repo
    [ -e "$copy/.git" ] || die "the manager '$manager' of $name has no copy of the project"
    main=$(cat "$state/$name/main-branch")
    cd "$project"
    current=$(git symbolic-ref --short HEAD 2> /dev/null) || die "the project is on no branch: check one out first"
    if [ -z "$side" ]; then
      branch=$main
      [ "$current" = "$main" ] || die "the project is not on its main branch '$main': check it out first"
    else
      branch=$side
      [ "$side" != "$main" ] || die "'$side' is the project's main branch: that is 'workers take' without --branch"
    fi
    [ -z "$(git status --porcelain)" ] || die "the project has uncommitted changes: commit or set them aside first, so that what you review is the manager's work alone"
    # The manager's copy is the remote: nothing in it runs
    git fetch --quiet --no-tags "file://$copy" "refs/heads/$branch" || die "the branch '$branch' of the manager's copy could not be fetched"
    # A side branch is entered, and made first if the project does not have it: from the commit that the manager's branch and
    # the project's main branch share, so that what gets staged is what the manager's branch adds to it
    created=0
    if [ -n "$side" ]; then
      if git show-ref --verify --quiet "refs/heads/$side"; then
        if [ "$current" != "$side" ]; then git switch --quiet "$side"; fi
      else
        start=$(git merge-base FETCH_HEAD "refs/heads/$main") || die "the manager's branch '$side' shares no commit with the project's main branch '$main'"
        git switch --quiet -c "$side" "$start"
        created=1
      fi
    fi
    # Back to where you were, without a branch that this call made
    back() {
      if [ "$(git symbolic-ref --short HEAD)" != "$current" ]; then git switch --quiet "$current"; fi
      if [ "$created" = 1 ]; then git branch --quiet -D "$side"; fi
    }
    undo="git reset --hard"
    if [ "$current" != "$branch" ]; then undo="$undo && git switch $current"; fi
    if [ "$created" = 1 ]; then undo="$undo && git branch -D $side"; fi
    if git merge-base --is-ancestor FETCH_HEAD HEAD; then
      back
      echo "the manager's copy holds nothing that the project does not have"
      exit 0
    fi
    # One change set, staged and not committed: the branch's history in the project gets your commit and nobody else's
    if ! git merge --squash FETCH_HEAD; then
      echo "workers: the manager's work does not fit onto $branch without conflicts; resolve them, or undo with: $undo" >&2
      exit 1
    fi
    # git would propose the copies' commit messages, with their branch names, for your commit: the message is yours alone
    rm -f "$(git rev-parse --git-path SQUASH_MSG)"
    # The manager's copy may be behind the project's own commits and still bring nothing: say so instead of "staged"
    if git diff --cached --quiet; then
      back
      echo "the manager's copy holds nothing that the project does not have"
      exit 0
    fi
    # What the manager's records say about the project's whole suite on the commit that was taken; the change is staged either way
    "${status[@]}" --full-run "$name" "$manager" "$(git rev-parse FETCH_HEAD)"
    if [ -z "$side" ]; then
      echo "staged and not committed. Review with 'git diff --cached'; commit yourself, or send it back with '$undo'"
    else
      if [ "$created" = 1 ]; then kind="the new branch"; else kind="the branch"; fi
      echo "staged on $kind '$side' and not committed; the project is on that branch now. Review with 'git diff --cached'; commit yourself, or send it back with '$undo'"
    fi
    ;;
  found)
    large=0
    if [ "${2:-}" = --with-large-files ]; then
      large=1
      shift
    fi
    [ -z "${2:-}" ] || die "usage: workers found [--with-large-files]"
    inProject
    cd "$project"
    git rev-parse --verify --quiet "HEAD^{commit}" > /dev/null || die "$project has no commit yet: make the first commit yourself, then there is something to compare the found work with"
    # A branch name that is free: found/<date>, then found/<date>-2 and so on
    branch=found/$(date +%F)
    number=2
    while git show-ref --verify --quiet "refs/heads/$branch" || git for-each-ref --format=x "refs/heads/$branch-stash-*" | grep -q x; do
      branch=found/$(date +%F)-$number
      number=$((number + 1))
    done
    # The working tree as it lies there goes into an index of this command's own: tracked changes and untracked files, without
    # what the project ignores. The project's own index is only read
    mapfile -d "" untracked < <(git ls-files --others --exclude-standard -z)
    index=$(mktemp)
    trap 'rm -f "$index"' EXIT
    if [ -e "$(git rev-parse --git-path index)" ]; then cp "$(git rev-parse --git-path index)" "$index"; else rm -f "$index"; fi
    export GIT_INDEX_FILE=$index
    git add --all || die "the working tree could not be read; nothing was recorded"
    # Untracked files above the size limit would stay in the history for good: they are left out, and named
    left=()
    if [ "$large" = 0 ]; then
      for file in "${untracked[@]}"; do
        if [ -f "$file" ] && [ ! -L "$file" ] && [ "$(stat -c %s -- "$file")" -gt "$FOUND_LARGE_BYTES" ]; then
          git rm --quiet --cached -- "$file"
          left+=("$file")
        fi
      done
    fi
    tree=$(git write-tree)
    unset GIT_INDEX_FILE
    made=()
    if [ "$tree" != "$(git rev-parse "HEAD^{tree}")" ]; then
      commit=$(git commit-tree -p HEAD -m "The work as found on $(date +%F)" "$tree") || die "the commit could not be made; nothing was recorded"
      git branch "$branch" "$commit"
      made+=("$branch")
      echo "$branch:$(git diff --shortstat HEAD "$branch")"
    fi
    # Every stash becomes a branch beside it; files that a stash holds as untracked are in its third parent (<branch>^3)
    count=$(git rev-list --walk-reflogs --count refs/stash 2> /dev/null || echo 0)
    for ((entry = 0; entry < count; entry++)); do
      git branch "$branch-stash-$entry" "stash@{$entry}"
      made+=("$branch-stash-$entry")
      echo "$branch-stash-$entry: $(git log -1 --format=%s "stash@{$entry}")"
    done
    for file in "${left[@]}"; do
      echo "left out, larger than $(megabytes "$FOUND_LARGE_BYTES"): $file"
    done
    if [ "${#left[@]}" -gt 0 ]; then echo "(workers found --with-large-files records them too)"; fi
    if [ "${#made[@]}" = 0 ]; then
      echo "nothing to record: the working tree holds nothing but what is committed, ignored or left out, and there is no stash"
    else
      echo "The working tree, the index and the current branch are as they were. Files that the project ignores are not recorded; a manager sees them, read-only, when started with: pi --role manager --allow-ro $project"
    fi
    ;;
  *) die "usage: workers list | remove [--force] <project>/<branch>/<name> | restore <project>/<branch>/<name> | remove-session <project>-<digest> | take [--branch <name>] [<manager>] | found [--with-large-files] | approve [--without-form | --revoke] <project>/<branch>/<name> | status [--json] | watch [<options>]" ;;
esac
