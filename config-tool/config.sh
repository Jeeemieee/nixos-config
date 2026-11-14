# The upkeep command of nixos-config and nixos-secrets (see docs/UPKEEP.md); run by the user, outside any sandbox
#   config check                 run the checks on the staged content and record that exactly this content passed
#   config commit "<message>"    stage everything, check, confirm changes to protected files, commit and push
#   config update <what>         fetch new versions and run the checks: pi, extensions, search, system, dev, secrets or all
#   config guard                 the two gates of a commit; git's pre-commit hook calls it
# PROTECTED (a JSON file: repository name -> protected paths) and CHECK_COMMAND come from the build
die() {
  echo "config: $1" >&2
  exit 2
}
nixCommand() { nix --extra-experimental-features 'nix-command flakes' "$@"; }

## Step 1. Which repository this is; the command only works in the ones it has a list of protected files for
root=$(git rev-parse --show-toplevel 2> /dev/null) || die "this is not a git repository"
name=$(basename "$root")
if [ "$root" != "$HOME/repos/$name" ] || ! jq -e --arg name "$name" 'has($name)' "$PROTECTED" > /dev/null; then
  die "$root is not one of the repositories this command keeps: $(jq -r '[keys[] | "~/repos/" + .] | join(", ")' "$PROTECTED")"
fi
cd "$root"
# Where a passed check is recorded: a hidden folder of the home, which no pi sandbox sees
state=${XDG_STATE_HOME:-$HOME/.local/state}/config-checks/$name

# The staged content as one fingerprint: what a commit made now would contain
stagedTree() { git write-tree; }

# Refuse unless the folder holds exactly the staged content: the checks read the folder, a commit takes the staged content
requireStaged() {
  if ! git diff --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    die "the folder differs from the staged content (see git status); stage everything with 'git add -A', or use: config commit \"<message>\""
  fi
}

runChecks() {
  if [ -n "$CHECK_COMMAND" ]; then
    "$CHECK_COMMAND" "$root"
  elif [ -e flake.nix ]; then
    nixCommand flake check "path:$root"
  else
    # A repository of secrets: every file below secrets/ must be encrypted
    local file failed=0
    for file in secrets/*; do
      [ -f "$file" ] || continue
      if [ "$(sops filestatus "$file" 2> /dev/null | jq -r '.encrypted')" != true ]; then
        echo "config: $file is not encrypted" >&2
        failed=1
      fi
    done
    [ "$failed" = 0 ]
  fi
}

check() {
  requireStaged
  local tree
  tree=$(stagedTree)
  echo "config: running the checks of $name ..."
  runChecks || die "the checks failed; nothing was recorded"
  mkdir -p "$state"
  touch "$state/$tree"
  echo "config: the checks passed for this content ($tree)"
}

# The two gates of a commit
guard() {
  local tree status path extra sensitive=() protectedPath
  tree=$(stagedTree)

  ## Gate 1. Changes to protected files, and files added to or removed from a folder whose files are all loaded, need a typed yes
  while IFS= read -r -d "" status; do
    IFS= read -r -d "" path
    extra=
    case "$status" in R* | C*) IFS= read -r -d "" extra ;; esac
    for candidate in "$path" $extra; do
      while IFS= read -r protectedPath; do
        case "$candidate" in "$protectedPath" | "$protectedPath"/*) sensitive+=("$status $candidate") ;; esac
      done < <(jq -r --arg name "$name" '.[$name][]' "$PROTECTED")
      case "$status:$candidate" in
        [ADRC]*:modules/*) sensitive+=("$status $candidate (a module added, removed or renamed: every file below modules/ is loaded)") ;;
      esac
    done
  done < <(git diff --cached --name-status -z)
  if [ "${#sensitive[@]}" -gt 0 ]; then
    echo "config: this commit changes protected files of $name:"
    printf '  %s\n' "${sensitive[@]}" | sort -u
    local answer=
    read -r -p "Type yes to commit these changes: " answer < "${CONFIG_GUARD_TTY:-/dev/tty}" \
      || die "no terminal to ask on, so the changes to protected files are not committed"
    [ "$answer" = yes ] || die "not confirmed; nothing was committed"
  fi

  ## Gate 2. The checks passed on exactly this content
  [ -e "$state/$tree" ] || die "no passed check is recorded for this content; run: config check"
}

commit() {
  [ -n "${1:-}" ] || die "usage: config commit \"<message>\""
  git add -A
  if git diff --cached --quiet; then die "there is nothing to commit"; fi
  git status --short
  check
  guard
  # The same two gates have just been passed here, so git's own hook does not ask a second time
  git commit --no-verify -m "$1"
  git push
}

# The version of a package in the system the virtual machine is built from
packageVersion() { nixCommand eval --raw "path:$root#nixosConfigurations.mimir-vm.pkgs.$1.version" 2> /dev/null || echo unknown; }

update() {
  [ -e flake.nix ] || die "update is for nixos-config"
  local what=${1:-} inputs=()
  # Everything that is not one of the separately kept pins
  mapfile -t system < <(nixCommand flake metadata --json "path:$root" | jq -r '.locks.nodes.root.inputs | keys[]' | grep -vxE 'nixpkgs-pi|nixpkgs-search|nixpkgs-unstable|nixos-secrets')
  case "$what" in
    pi) inputs=(nixpkgs-pi) ;;
    search) inputs=(nixpkgs-search) ;;
    secrets) inputs=(nixos-secrets) ;;
    dev)
      echo "config: this moves the development environments (PETSc, CUDA); a project keeps its versions until it runs 'nix flake update blocks'"
      inputs=(nixpkgs-unstable)
      ;;
    system) inputs=("${system[@]}") ;;
    all) inputs=("${system[@]}" nixpkgs-pi nixpkgs-search nixos-secrets) ;;
    extensions) ;;
    *) die "usage: config update pi|extensions|search|system|dev|secrets|all" ;;
  esac
  local before
  before=$(mktemp)
  cp flake.lock "$before"
  local piBefore searchBefore
  piBefore=$(packageVersion pi-coding-agent)
  searchBefore=$(packageVersion searxng)

  if [ "${#inputs[@]}" -gt 0 ]; then
    nixCommand flake update "${inputs[@]}" --flake "path:$root"
  fi
  case "$what" in extensions | all) UPDATE_EXTENSIONS modules/dev/pi.nix ;; esac

  echo
  echo "config: what changed"
  jq -r --slurpfile old "$before" '
    .nodes as $new | $old[0].nodes as $was
    | $new | to_entries[]
    | select(.value.locked != null and ($was[.key].locked.rev // $was[.key].locked.narHash) != (.value.locked.rev // .value.locked.narHash))
    | "  \(.key): \(($was[.key].locked.lastModified // 0) | strftime("%Y-%m-%d")) -> \((.value.locked.lastModified // 0) | strftime("%Y-%m-%d"))"' flake.lock
  rm -f "$before"
  echo "  pi: $piBefore -> $(packageVersion pi-coding-agent)"
  echo "  SearXNG: $searchBefore -> $(packageVersion searxng)"
  git --no-pager diff --stat

  echo
  echo "config: running the checks on the updated configuration ..."
  runChecks || die "the checks fail with these versions; nothing is committed. Undo with: git checkout flake.lock modules/dev/pi.nix"
  echo "config: the checks pass. Review with 'git diff', then: config commit \"<message>\""
}

case "${1:-}" in
  check) check ;;
  guard) guard ;;
  commit) commit "${2:-}" ;;
  update) update "${2:-}" ;;
  *) die "usage: config check | config commit \"<message>\" | config update pi|extensions|search|system|dev|secrets|all" ;;
esac
