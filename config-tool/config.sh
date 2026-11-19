# The upkeep command of nixos-config and nixos-secrets (see docs/UPKEEP.md); run by the user, outside any sandbox
#   config check                 run the checks on the staged content and record that exactly this content passed
#   config commit "<message>"    stage everything, check, confirm changes to protected files, commit and push
#   config update <what>         fetch new versions and run the checks: pi, extensions, search, system, dev, secrets or all
#   config build <host> [vm]     build a host's system, or its virtual machine, from the last commit
#   config switch                build this machine's system from the last commit and switch to it
#   config install <arguments>   run the install tool (docs/INSTALL.md) from the last commit
#   config guard                 the two gates of a commit; git's pre-commit hook calls it
#   config guard-push <remote>   the same gates for what a push sends; git's pre-push hook calls it
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
    # A repository of secrets: every value in every file below secrets/, at any depth, must be encrypted
    # sops says "encrypted" of a file as soon as it has sops' own block, also when a plain value was added by hand, so every
    # value is looked at: all but sops' own block must have the form sops writes. Only the names are printed, never a value
    local file plain name failed=0
    while IFS= read -r -d "" file; do
      case "$file" in
        *.yaml | *.yml | *.json) ;;
        *)
          echo "config: ${file#"$exported"/} is of a kind this check cannot read (it reads .yaml, .yml and .json), so it cannot say that it is encrypted" >&2
          failed=1
          continue
          ;;
      esac
      if ! plain=$(yq -o=json '.' "$file" 2> /dev/null | jq -r '
        if (type != "object") or (has("sops") | not) then "(the whole file: it has no block of sops)"
        else [paths(scalars) as $path | select($path[0] != "sops") | select((getpath($path) | type) != "string" or (getpath($path) | test("^ENC\\[AES256_GCM,data:[^,]*,iv:[^,]*,tag:[^,]*,type:[a-z]+\\]$") | not)) | $path | map(tostring) | join(".")][]
        end'); then
        plain="(the whole file: it cannot be read)"
      fi
      if [ -n "$plain" ]; then
        while IFS= read -r name; do echo "config: ${file#"$exported"/} is not encrypted: $name" >&2; done <<< "$plain"
        failed=1
      fi
    done < <(find "$exported/secrets" -type f -print0 2> /dev/null)
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

# Gate 1 for a change, given as the arguments of `git diff` (--cached for a commit, two commits for a push):
# changes to protected files, and every change below modules/, where all files are loaded, need one typed yes
confirmChanges() {
  local action=$1 status path extra sensitive=() sensitivePaths=() modules=() shown=() protectedPath isProtected
  shift
  while IFS= read -r -d "" status; do
    IFS= read -r -d "" path
    extra=
    case "$status" in R* | C*) IFS= read -r -d "" extra ;; esac
    for candidate in "$path" $extra; do
      isProtected=0
      while IFS= read -r protectedPath; do
        case "$candidate" in
          "$protectedPath" | "$protectedPath"/*) isProtected=1 ;;
        esac
      done < <(jq -r --arg name "$name" '.[$name][]' "$PROTECTED")
      if [ "$isProtected" = 1 ]; then
        sensitive+=("$status $candidate")
        sensitivePaths+=("$candidate")
      elif [[ $candidate == modules/* ]]; then
        case "$status" in
          M*) modules+=("$status $candidate") ;;
          *)
            sensitive+=("$status $candidate (a module added, removed or renamed)")
            sensitivePaths+=("$candidate")
            ;;
        esac
      elif [ ! -e flake.nix ] && [[ $status == A* ]]; then
        # A repository of secrets is pushed and then copied to the Nix store of every machine that builds: a new file there,
        # outside the places that are checked, is shown before it leaves
        sensitive+=("$status $candidate (a new file in a repository of secrets)")
        sensitivePaths+=("$candidate")
      fi
    done
  done < <(git diff "$@" --name-status -z)
  if [ "${#sensitive[@]}" -gt 0 ] || [ "${#modules[@]}" -gt 0 ]; then
    if [ "${#sensitive[@]}" -gt 0 ]; then
      echo "config: this $action changes protected files of $name:"
      printf '  %s\n' "${sensitive[@]}" | sort -u
    fi
    if [ "${#modules[@]}" -gt 0 ]; then
      # Not protected, yet loaded like every file below modules/: a module can set what another one sets
      echo "config: this $action changes modules of $name, all of which are loaded into the system:"
      printf '  %s\n' "${modules[@]}" | sort -u
    fi
    # What changes, shown by git itself before the question: a summary of all of it, then the protected files and the added or
    # removed modules in full, on a terminal in git's own viewer (q closes it). The changed modules are for `git diff`
    echo
    for path in "${modules[@]}"; do shown+=("${path#* }"); done
    git --no-pager diff "$@" --stat -- "${sensitivePaths[@]}" "${shown[@]}"
    if [ "${#sensitivePaths[@]}" -gt 0 ]; then
      if [ -t 1 ]; then
        git diff "$@" -- "${sensitivePaths[@]}"
      else
        git --no-pager diff "$@" -- "${sensitivePaths[@]}"
      fi
    fi
    local answer=
    read -r -p "Type yes to $action these changes: " answer < "${CONFIG_GUARD_TTY:-/dev/tty}" \
      || die "no terminal to ask on, so these changes are not accepted"
    [ "$answer" = yes ] || die "not confirmed; nothing was done"
  fi
}

# The two gates of a commit
guard() {
  local tree
  refuseIgnoredModules
  tree=$(stagedTree)

  ## Gate 1. The user's yes to what the commit changes
  confirmChanges commit --cached
  # Remembered for the push: this content was shown and confirmed as a step from the commit before it
  mkdir -p "$state"
  touch "$state/$tree.confirmed"

  ## Gate 2. The checks passed on exactly this content
  [ -e "$state/$tree" ] || die "no passed check is recorded for this content; run: config check"
}

# The same two gates for what a push sends: git's pre-push hook calls this with the remote's name, and one line per branch on
# its input: <local ref> <local commit> <remote ref> <remote commit>
# A commit made by `config commit`, or by `git commit` with the hook, has passed both gates and passes here without a word.
# What arrived another way (a merge, a fast-forward, a cherry-pick, a rebase, a commit with --no-verify) has not
guardPush() {
  local remote=${1:-origin} localRef localCommit remoteRef remoteCommit zero base tree unconfirmed commit
  zero=$(git hash-object --stdin < /dev/null | tr '0-9a-f' '0')
  while read -r localRef localCommit remoteRef remoteCommit; do
    # A branch that is removed from the remote sends nothing
    [ "$localCommit" != "$zero" ] || continue
    ## Gate 2. The checks passed on exactly the content that the branch will have
    tree=$(git rev-parse "$localCommit^{tree}")
    [ -e "$state/$tree" ] || die "no passed check is recorded for the content of $localRef: check it out and run: config check"

    ## Gate 1. The commits that are sent, and of them those that were not confirmed one by one when they were made
    if [ "$remoteCommit" = "$zero" ]; then
      # A branch that is new on the remote: everything the remote does not have yet
      mapfile -t sent < <(git rev-list "$localCommit" --not --remotes="$remote")
      base=$(git rev-list --boundary "$localCommit" --not --remotes="$remote" | sed -n 's/^-//p' | head -n 1)
      # Nothing of it is on the remote: compared with an empty folder
      [ -n "$base" ] || base=$(git hash-object -t tree /dev/null)
    else
      git cat-file -e "$remoteCommit^{commit}" 2> /dev/null || die "the remote's $remoteRef is at a commit this repository does not have: fetch first"
      mapfile -t sent < <(git rev-list "$localCommit" --not "$remoteCommit")
      base=$remoteCommit
    fi
    unconfirmed=()
    for commit in "${sent[@]}"; do
      [ -e "$state/$(git rev-parse "$commit^{tree}").confirmed" ] || unconfirmed+=("$commit")
    done
    if [ "${#unconfirmed[@]}" -gt 0 ]; then
      echo "config: $localRef holds ${#unconfirmed[@]} commit(s) that did not pass the commit guard (merged, picked, rebased, or committed without it):"
      git --no-pager log --no-walk --format='  %h %s' "${unconfirmed[@]}"
      echo "config: everything they hold leaves this machine with the push; what the branch changes on the remote, all commits together:"
      confirmChanges push "$base" "$localCommit"
      touch "$state/$tree.confirmed"
    fi
  done
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
  mapfile -t system < <(nixCommand flake metadata --json "path:$root" | jq -r '.locks.nodes.root.inputs | keys[]' | grep -vxE 'nixpkgs-pi|nixpkgs-search|nixpkgs-unstable|nixos-secrets|dev-env')
  case "$what" in
    pi) inputs=(nixpkgs-pi) ;;
    search) inputs=(nixpkgs-search) ;;
    secrets) inputs=(nixos-secrets) ;;
    dev)
      echo "config: this moves the development environments (PETSc, CUDA); a project keeps its versions until it runs 'nix flake update blocks'"
      # The blocks' own lock first, which projects get; then this repository's copy of it (dev-env-lock-in-step)
      nixCommand flake update --flake "path:$root/dev-env"
      inputs=(dev-env)
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
  runChecks "$(folderTree)" || die "the checks fail with these versions; nothing is committed. Undo with: git checkout flake.lock dev-env/flake.lock modules/dev/pi.nix"
  echo "config: the checks pass. Review with 'git diff', then: config commit \"<message>\""
}

case "${1:-}" in
  check) check ;;
  guard) guard ;;
  guard-push) guardPush "${2:-}" ;;
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
