# The folders and scratch areas of workers as ZFS datasets; runs as root through sudo, called by the pi launcher (see docs/WORKERS.md)
#   worker-datasets ensure <project> <branch> <name>              create what is missing and mount it: the worker's folder, its scratch area,
#                                                                 and the project's instructions and archive folders
#   worker-datasets ensure-area <project> <branch> <name>         the scratch area alone, for a session without a worker's folder
#   worker-datasets ensure-knowledge <project> <branch>           the project's common knowledge and one branch's knowledge
#   worker-datasets snapshot <project> <branch> <name> <label>    snapshot the scratch area
#   worker-datasets rollback <project> <branch> <name> <label>    return it to that snapshot; later snapshots of it are destroyed
#   worker-datasets drop <project> <branch> <name> <label>        destroy that snapshot
#   worker-datasets list <project> <branch> <name>                the scratch area's snapshots
#   worker-datasets retire <project> <branch> <name>              remove a worker: its folder is unmounted and marked, and kept for
#                                                                 HOLD_DAYS days; its scratch area is destroyed at once
#   worker-datasets restore <project> <branch> <name>             undo that while the folder is kept
#   worker-datasets drop-area <project> <branch> <name>           destroy a scratch area, which holds only what can be made again
#   worker-datasets status                                        every worker dataset with its size, limit and mark
#   worker-datasets mount-all                                     mount every worker dataset (at boot, after the two parents)
#   worker-datasets expire                                        destroy the folders whose mark is older than HOLD_DAYS days; only for
#                                                                 the system's timer: no caller through sudo can destroy a folder
# ZFS on Linux lets only root mount, so this cannot be delegated with `zfs allow`
# It acts only below the two parents, WORKERS_PATH and SCRATCH_PATH, and only while each is its dataset, mounted, with a top folder that
# belongs to root: nothing running as the caller can then rename or replace a folder on the way to a mount point
# Every name is checked, and dataset names and mount points are built from them: the caller chooses neither
# WORKERS_DATASET, WORKERS_PATH, SCRATCH_DATASET, SCRATCH_PATH, OWNER and the three quotas come from the system configuration
# The name check below must not depend on the caller's language settings, which sudo passes on
export LC_ALL=C
die() {
  echo "worker-datasets: $1" >&2
  exit 2
}
[ "$(id -u)" = 0 ] || die "must run as root, through sudo"
[ "${SUDO_USER:-$OWNER}" = "$OWNER" ] || die "only $OWNER may manage worker datasets"
validName() { [[ $1 =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$ ]]; }
exists() { zfs list -H -o name "$1" > /dev/null 2>&1; }

# Refuse unless a parent is what the system configuration declares: its dataset, mounted there, the top folder root's and not writable for others
checkParent() {
  local dataset=$1 path=$2
  [ "$(realpath -e -- "$path" 2> /dev/null)" = "$path" ] || die "refusing: $path is missing or is reached through a link"
  [ "$(findmnt -rn -o SOURCE,FSTYPE --mountpoint "$path" 2> /dev/null)" = "$dataset zfs" ] || die "refusing: $dataset is not mounted at $path"
  [ "$(stat -c '%u %a' -- "$path")" = "0 755" ] || die "refusing: $path does not belong to root with mode 755"
}

# Make each grouping level as root, and refuse an existing one that the user could rename or replace
checkAncestors() {
  local root=$1 relative=$2 parent path level levels
  parent=$(dirname "$relative")
  [ "$parent" = . ] && return
  path=$root
  IFS=/ read -r -a levels <<< "$parent"
  for level in "${levels[@]}"; do
    path=$path/$level
    if [ ! -e "$path" ] && [ ! -L "$path" ]; then
      install -d -o root -g root -m 755 -- "$path"
    fi
    [ "$(realpath -e -- "$path" 2> /dev/null)" = "$path" ] || die "refusing: $path is missing or is reached through a link"
    [ "$(stat -c '%u %a' -- "$path")" = "0 755" ] || die "refusing: $path does not belong to root with mode 755; correct it with: sudo chown root:root $path && sudo chmod 755 $path"
  done
}

# Mount a dataset at its own mount point unless it is mounted, and check where it arrived
mountDataset() {
  local dataset=$1 path relative
  path=$(zfs get -H -o value mountpoint "$dataset")
  if [[ $path = "$WORKERS_PATH/"* ]]; then
    relative=${path#"$WORKERS_PATH/"}
    checkAncestors "$WORKERS_PATH" "$relative"
    # Knowledge paths are stable user entry points: never recreate one that was moved or replaced
    if [[ $relative =~ ^[^/]+/knowledge/[^/]+$ ]]; then
      [ ! -L "$path" ] || die "refusing: $path is reached through a link"
      [ -d "$path" ] || die "refusing: $path is missing or moved"
      [ "$(realpath -e -- "$path" 2> /dev/null)" = "$path" ] || die "refusing: $path is reached through a link"
    fi
  elif [[ $path = "$SCRATCH_PATH/"* ]]; then
    checkAncestors "$SCRATCH_PATH" "${path#"$SCRATCH_PATH/"}"
  else
    die "refusing: the mount point of $dataset is outside the two worker parents"
  fi
  if [ "$(zfs get -H -o value mounted "$dataset")" != yes ]; then zfs mount "$dataset"; fi
  [ "$(findmnt -rn -o SOURCE --mountpoint "$path" 2> /dev/null)" = "$dataset" ] || die "$dataset did not arrive at $path"
}

# Create a dataset that belongs to the caller, with a limit, and mount it; the levels above it only group and are never mounted
createOwned() {
  local parent=$1 parentPath=$2 relative=$3 quota=$4 level dataset=$1
  checkAncestors "$parentPath" "$relative"
  for level in $(dirname "$relative" | tr / ' '); do
    if [ "$level" != . ]; then
      dataset=$dataset/$level
      exists "$dataset" || zfs create -o canmount=off -o mountpoint=none "$dataset"
    fi
  done
  dataset=$parent/$relative
  if ! exists "$dataset"; then
    # noauto: mounted here and by mount-all, after the parent; never by `zfs mount -a` underneath it
    zfs create -o canmount=noauto -o mountpoint="$parentPath/$relative" -o quota="$quota" "$dataset"
    mountDataset "$dataset"
    chown --no-dereference "$OWNER": "$parentPath/$relative"
    chmod 700 "$parentPath/$relative"
  else
    mountDataset "$dataset"
  fi
}

# Make one knowledge leaf without ever mounting over an existing ordinary path
createKnowledge() {
  local project=$1 relative=$1/knowledge/$2 dataset=$WORKERS_DATASET/$1/knowledge/$2 path=$WORKERS_PATH/$1/knowledge/$2
  if exists "$dataset"; then
    [ "$(zfs get -H -o value mountpoint "$dataset")" = "$path" ] || die "refusing: $path is missing or moved"
  else
    checkAncestors "$WORKERS_PATH" "$relative"
    [ ! -e "$path" ] && [ ! -L "$path" ] || die "refusing: $path already exists without its knowledge dataset"
    install -d -o root -g root -m 755 -- "$path"
  fi
  createOwned "$WORKERS_DATASET" "$WORKERS_PATH" "$relative" "$FOLDER_QUOTA"
  [ "$(stat -c '%U %a' -- "$path")" = "$OWNER 700" ] || die "refusing: $path does not belong to $OWNER with mode 700"
}

action=${1:-}
checkParent "$WORKERS_DATASET" "$WORKERS_PATH"
checkParent "$SCRATCH_DATASET" "$SCRATCH_PATH"

if [ "$action" = status ]; then
  zfs list -H -p -r -o name,used,quota,workers:retired "$WORKERS_DATASET" "$SCRATCH_DATASET"
  exit 0
fi
if [ "$action" = expire ]; then
  [ -z "${SUDO_USER:-}" ] || die "only the system's timer destroys a removed worker's folder"
  now=$(date +%s)
  zfs list -H -r -o name,workers:retired "$WORKERS_DATASET" | while IFS=$'\t' read -r dataset retired; do
    if [[ $retired =~ ^[0-9]+$ ]] && [ $((now - retired)) -gt $((HOLD_DAYS * 86400)) ]; then
      echo "destroying $dataset, removed $(((now - retired) / 86400)) days ago"
      zfs destroy -r "$dataset"
    fi
  done
  exit 0
fi
if [ "$action" = mount-all ]; then
  for parent in "$WORKERS_DATASET" "$SCRATCH_DATASET"; do
    zfs list -H -r -o name,canmount "$parent" | while IFS=$'\t' read -r dataset canmount; do
      if [ "$canmount" = noauto ]; then mountDataset "$dataset"; fi
    done
  done
  exit 0
fi

if [ "$action" = ensure-knowledge ]; then
  [ "$#" = 3 ] || die "usage: worker-datasets ensure-knowledge <project> <branch>"
  project=$2
  branch=$3
  validName "$project" || die "invalid project name '$project'"
  validName "$branch" || die "invalid branch name '$branch'"
  case "$branch" in manager | archive | instructions | knowledge | common | plain | old) die "'$branch' cannot be a knowledge branch name" ;; esac
  createKnowledge "$project" common
  createKnowledge "$project" "$branch"
  exit 0
fi

[ "$#" -ge 4 ] || die "usage: worker-datasets ensure|ensure-area|retire|restore|drop-area|snapshot|rollback|drop|list <project> <branch> <name> [<label>]"
project=$2
branch=$3
name=$4
label=${5:-}
validName "$project" || die "invalid project name '$project'"
validName "$branch" || die "invalid branch name '$branch'"
validName "$name" || die "invalid worker name '$name'"
# These are folders beside the branches; old is the user's own, never a worker's
case "$branch" in instructions | archive | knowledge | old) die "'$branch' cannot be a branch name: the project's folder of that name is in its place" ;; esac
# The manager and ordinary sessions use these two internal names, not branch names
if [ "$branch" = plain ] && [ "$action" = ensure ]; then
  die "'plain' cannot be a branch name: it is reserved for ordinary sessions"
fi
area=$SCRATCH_DATASET/$project/$branch/$name
folder=$WORKERS_DATASET/$project/$branch/$name
# The time a folder was removed at, or nothing
retired() { zfs get -H -o value workers:retired "$folder" 2> /dev/null | grep -E '^[0-9]+$' || true; }

case "$action" in
  ensure)
    # A removed worker keeps its name while its folder is kept: a new one must not inherit its snapshots
    if [ -n "$(retired)" ]; then
      die "the worker $project/$branch/$name was removed and its folder is kept until $(date -d "@$(($(retired) + HOLD_DAYS * 86400))" +%F): restore it with 'workers restore $project/$branch/$name', or choose another name"
    fi
    createOwned "$WORKERS_DATASET" "$WORKERS_PATH" "$project/$branch/$name" "$FOLDER_QUOTA"
    # A new scratch area is snapshotted as it is made, empty: `workers approve --empty-scratch` returns it to that
    if exists "$area"; then
      createOwned "$SCRATCH_DATASET" "$SCRATCH_PATH" "$project/$branch/$name" "$AREA_QUOTA"
    else
      createOwned "$SCRATCH_DATASET" "$SCRATCH_PATH" "$project/$branch/$name" "$AREA_QUOTA"
      zfs snapshot "$area@created"
    fi
    createOwned "$WORKERS_DATASET" "$WORKERS_PATH" "$project/instructions" "$INSTRUCTIONS_QUOTA"
    # Only the user's own tools write the archive; it is limited by the parent
    createOwned "$WORKERS_DATASET" "$WORKERS_PATH" "$project/archive" none
    ;;
  retire)
    exists "$folder" || die "there is no worker $project/$branch/$name"
    # A worker already marked by an older interrupted removal keeps that state; a later call only finishes its scratch area
    if [ -n "$(retired)" ]; then
      if exists "$area"; then zfs destroy -r "$area" || die "the earlier removal of $project/$branch/$name is still blocked because its scratch area is in use"; fi
      exit 0
    fi

    # A new removal first detaches both places while remembering exactly what must be restored on refusal
    areaMounted=no
    folderMounted=no
    if exists "$area" && [ "$(zfs get -H -o value mounted "$area")" = yes ]; then
      areaMounted=yes
      zfs unmount "$area" || die "the scratch area of $project/$branch/$name is in use (a terminal or a program is in it); nothing was changed"
    fi
    if [ "$(zfs get -H -o value mounted "$folder")" = yes ]; then
      folderMounted=yes
      if ! zfs unmount "$folder"; then
        if [ "$areaMounted" = yes ]; then zfs mount "$area"; fi
        die "the folder of $project/$branch/$name is in use (a terminal or a program is in it); nothing was changed"
      fi
    fi

    # Mark the kept folder, then destroy the disposable area; a failed destruction rolls every property and mount back
    zfs set canmount=off "workers:retired=$(date +%s)" "$folder"
    if exists "$area" && ! zfs destroy -r "$area"; then
      zfs inherit workers:retired "$folder"
      zfs set canmount=noauto "$folder"
      if [ "$folderMounted" = yes ]; then mountDataset "$folder"; fi
      if [ "$areaMounted" = yes ]; then mountDataset "$area"; fi
      die "the scratch area of $project/$branch/$name is in use; the removal was rolled back and nothing was changed"
    fi
    ;;
  restore)
    [ -n "$(retired)" ] || die "the worker $project/$branch/$name is not removed"
    zfs inherit workers:retired "$folder"
    zfs set canmount=noauto "$folder"
    mountDataset "$folder"
    ;;
  drop-area)
    exists "$area" || die "there is no scratch area $area"
    zfs destroy -r "$area"
    ;;
  ensure-area)
    createOwned "$SCRATCH_DATASET" "$SCRATCH_PATH" "$project/$branch/$name" "$AREA_QUOTA"
    ;;
  snapshot | rollback | drop)
    validName "$label" || die "$action needs a label of letters, digits, '.', '_' or '-'"
    exists "$area" || die "there is no scratch area $area"
    case "$action" in
      snapshot) zfs snapshot "$area@$label" ;;
      rollback) zfs rollback -r "$area@$label" ;;
      drop) zfs destroy "$area@$label" ;;
    esac
    ;;
  list)
    exists "$area" || die "there is no scratch area $area"
    zfs list -H -t snapshot -o name,creation,used "$area"
    ;;
  *) die "unknown action '$action'" ;;
esac
