# The upkeep command of nixos-config and nixos-secrets (see docs/UPKEEP.md); run by the user, outside any sandbox
#   config check                 run the checks on the staged content and record that exactly this content passed
#   config commit "<message>"    stage everything, check, confirm changes to protected files, commit and push
#   config update <what>         fetch new versions and run the checks: pi, extensions, search, system, dev, secrets or all
#   config build <host> [vm]     build a host's system, or its virtual machine, from the last commit
#   config switch                build this machine's system from the last commit and switch to it
#   config install <arguments>   run the install tool (docs/INSTALL.md) from the last commit
#   config guard                 the two gates of a commit; git's pre-commit hook calls it
# The checks and every build read the content of a commit, exported from git, and never the folder: a file that git ignores or
# that is not committed takes no part in them
# PROTECTED (a JSON file: repository name -> protected paths), CHECK_COMMAND and BUILD_COMMAND come from the build
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

# Refuse unless the folder holds exactly the staged content: the checks take the staged content, as a commit does, and a
# check that passes without a change its user has just made would mislead
requireStaged() {
  if ! git diff --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
    die "the folder differs from the staged content (see git status); stage everything with 'git add -A', or use: config commit \"<message>\""
  fi
}

# What a commit of the whole folder would contain, without changing what is staged
folderTree() {
  local index tree
  index=$(mktemp)
  cp "$(git rev-parse --git-path index)" "$index"
  GIT_INDEX_FILE=$index git add -A
  tree=$(GIT_INDEX_FILE=$index git write-tree)
  rm -f "$index"
  echo "$tree"
}

# Every file below modules/ is loaded when the folder is built. One that git ignores is in no commit and in no git status,
# so it is refused before anything else is said about the content
refuseIgnoredModules() {
  local ignored file
  ignored=$(git ls-files --others --ignored --exclude-standard -- modules)
  if [ -n "$ignored" ]; then
    echo "config: git ignores these files below modules/, where every file is loaded:" >&2
    while IFS= read -r file; do echo "  $file" >&2; done <<< "$ignored"
    die "remove them, or the rule in .gitignore that hides them"
  fi
}

# A tree of git as a new folder, byte for byte as committed: no filter, attribute or setting of the repository changes a
# file on the way, and nothing that is not in the tree is there
exported=
exportTree() {
  local tree=$1 meta path mode object
  exported=$(mktemp -d "${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/config-export.XXXXXX")
  trap 'rm -rf "$exported"' EXIT
  while IFS=$'\t' read -r -d "" meta path; do
    read -r mode _ object <<< "$meta"
    mkdir -p "$exported/$(dirname "$path")"
    case "$mode" in
      120000) ln -s "$(git cat-file blob "$object")" "$exported/$path" ;;
      160000) die "the content holds a submodule ($path), which this command does not export" ;;
      *)
        git cat-file blob "$object" > "$exported/$path"
        if [ "$mode" = 100755 ]; then chmod +x "$exported/$path"; fi
        ;;
    esac
  done < <(git ls-tree -r -z "$tree")
}

# The checks of a tree, on its export
runChecks() {
  exportTree "$1"
  if [ -n "$CHECK_COMMAND" ]; then
    "$CHECK_COMMAND" "$exported"
  elif [ -e "$exported/flake.nix" ]; then
    nixCommand flake check "path:$exported"
  else
    # A repository of secrets: every file below secrets/ must be encrypted
    local file failed=0
    for file in "$exported"/secrets/*; do
      [ -f "$file" ] || continue
      if [ "$(sops filestatus "$file" 2> /dev/null | jq -r '.encrypted')" != true ]; then
        echo "config: ${file#"$exported"/} is not encrypted" >&2
        failed=1
      fi
    done
    [ "$failed" = 0 ]
  fi
}

check() {
  requireStaged
  refuseIgnoredModules
  local tree
  tree=$(stagedTree)
  echo "config: running the checks of $name ..."
  runChecks "$tree" || die "the checks failed; nothing was recorded"
  mkdir -p "$state"
  touch "$state/$tree"
  echo "config: the checks passed for this content ($tree)"
}

# The last commit as a folder, for a build: only if the folder holds nothing else and the checks passed on exactly that commit
exportCheckedCommit() {
  [ -e flake.nix ] || die "this is for nixos-config"
  if [ -n "$(git status --porcelain)" ]; then
    die "the folder differs from the last commit (see git status), and a build takes the commit: commit first with: config commit \"<message>\""
  fi
  local tree
  tree=$(git rev-parse 'HEAD^{tree}')
  [ -e "$state/$tree" ] || die "no passed check is recorded for the last commit; run: config check"
  exportTree "$tree"
}

# Runs a build step on the exported commit: nix or nixos-rebuild, or the stand-in of this command's own test
buildStep() {
  if [ -n "$BUILD_COMMAND" ]; then "$BUILD_COMMAND" "$exported" "$@"; else "$@"; fi
}

build() {
  local host=${1:-} what=${2:-system} attribute
  [[ $host =~ ^[A-Za-z0-9-]+$ ]] || die "usage: config build <host> [vm]"
  case "$what" in
    system) attribute=toplevel ;;
    vm) attribute=vm ;;
    *) die "usage: config build <host> [vm]" ;;
  esac
  exportCheckedCommit
  buildStep nixCommand build --out-link "$root/result" "path:$exported#nixosConfigurations.$host.config.system.build.$attribute"
  echo "config: built the $what of $host from the last commit; see $root/result"
}

switch() {
  exportCheckedCommit
  if [ -z "$BUILD_COMMAND" ] && ! command -v nixos-rebuild > /dev/null; then
    die "switch is for a NixOS machine; here: config build <host>"
  fi
  # The system is evaluated and built as the user; only its activation asks for sudo's password
  buildStep nixos-rebuild switch --flake "path:$exported#$(hostname)" --ask-sudo-password
}

install() {
  exportCheckedCommit
  # The tool itself and the system it installs both come from the exported commit; paths in its arguments stay relative to here
  INSTALL_FLAKE=$exported buildStep nixCommand run "path:$exported#install" -- "$@"
}

# The two gates of a commit
guard() {
  local tree status path extra sensitive=() sensitivePaths=() protectedPath
  refuseIgnoredModules
  tree=$(stagedTree)

  ## Gate 1. Changes to protected files, and files added to or removed from a folder whose files are all loaded, need a typed yes
  while IFS= read -r -d "" status; do
    IFS= read -r -d "" path
    extra=
    case "$status" in R* | C*) IFS= read -r -d "" extra ;; esac
    for candidate in "$path" $extra; do
      while IFS= read -r protectedPath; do
        case "$candidate" in
          "$protectedPath" | "$protectedPath"/*)
            sensitive+=("$status $candidate")
            sensitivePaths+=("$candidate")
            ;;
        esac
      done < <(jq -r --arg name "$name" '.[$name][]' "$PROTECTED")
      case "$status:$candidate" in
        [ADRC]*:modules/*)
          sensitive+=("$status $candidate (a module added, removed or renamed: every file below modules/ is loaded)")
          sensitivePaths+=("$candidate")
          ;;
      esac
    done
  done < <(git diff --cached --name-status -z)
  if [ "${#sensitive[@]}" -gt 0 ]; then
    echo "config: this commit changes protected files of $name:"
    printf '  %s\n' "${sensitive[@]}" | sort -u
    # What changes in them, shown by git itself before the question: on a terminal in git's own viewer (q closes it)
    echo
    git --no-pager diff --cached --stat -- "${sensitivePaths[@]}"
    if [ -t 1 ]; then
      git diff --cached -- "${sensitivePaths[@]}"
    else
      git --no-pager diff --cached -- "${sensitivePaths[@]}"
    fi
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
  runChecks "$(folderTree)" || die "the checks fail with these versions; nothing is committed. Undo with: git checkout flake.lock modules/dev/pi.nix"
  echo "config: the checks pass. Review with 'git diff', then: config commit \"<message>\""
}

case "${1:-}" in
  check) check ;;
  guard) guard ;;
  commit) commit "${2:-}" ;;
  update) update "${2:-}" ;;
  build) build "${2:-}" "${3:-}" ;;
  switch) switch ;;
  install)
    shift
    install "$@"
    ;;
  *) die "usage: config check | config commit \"<message>\" | config update pi|extensions|search|system|dev|secrets|all | config build <host> [vm] | config switch | config install <arguments>" ;;
esac
