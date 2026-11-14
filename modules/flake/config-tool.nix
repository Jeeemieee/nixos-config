# The config command for the upkeep of this repository and nixos-secrets: checks, guarded commits, updates (docs/UPKEEP.md)
# `nix run .#config -- <command>`; also in the admin shell, and on the workstations as a program of the user
{
  flake.modules.homeManager.config-tool =
    { pkgs, ... }:
    let
      tool = import ../../config-tool pkgs { };
      # git runs this before every commit in the two repositories: the same two gates as `config commit`
      hooks = pkgs.writeTextFile {
        name = "config-guard-hooks";
        destination = "/pre-commit";
        executable = true;
        text = ''
          #!${pkgs.runtimeShell}
          exec ${tool}/bin/config guard
        '';
      };
    in
    {
      home.packages = [ tool ];

      # Named in the user's own git settings, which a pi sandbox only reads, so an agent cannot switch the hook off
      programs.git.includes = map (repository: {
        condition = "gitdir:~/repos/${repository}/";
        contents.core.hooksPath = "${hooks}";
      }) (builtins.attrNames (import ../../config-tool/protected.nix));
    };

  perSystem =
    { pkgs, ... }:
    let
      tool = import ../../config-tool pkgs { };
      # The real checks cannot run inside a check; this stand-in passes unless the content holds a file named BROKEN
      testTool = import ../../config-tool pkgs {
        checkCommand = pkgs.writeShellScript "config-stand-in-checks" ''[ ! -e "$1/BROKEN" ]'';
      };
    in
    {
      packages.config = tool;

      # The gates of a commit, in a scratch repository with a stand-in for the checks; and the extension updater against a stand-in registry
      checks.config-guard =
        pkgs.runCommand "config-guard-check"
          {
            nativeBuildInputs = [
              pkgs.git
              pkgs.age
              pkgs.sops
              pkgs.python3
            ];
          }
          ''
            export HOME=$TMPDIR/home GIT_CONFIG_GLOBAL=$TMPDIR/gitconfig
            export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.org GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.org
            git config --global init.defaultBranch main
            config=${testTool}/bin/config
            failed=0
            expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; failed=1; fi; }
            # Runs a command, answers its question from a file, and says whether it succeeded
            outcome() { local answer=$1; shift; echo "$answer" > "$TMPDIR/answer"; if CONFIG_GUARD_TTY=$TMPDIR/answer "$@" > "$TMPDIR/out" 2>&1; then echo accepted; else echo refused; fi; }
            said() { grep -q "$1" "$TMPDIR/out" || { echo "FAIL: expected the message: $1"; cat "$TMPDIR/out"; failed=1; }; }

            ## Step 1. A scratch nixos-config with a remote to push to
            repo=$HOME/repos/nixos-config
            mkdir -p "$repo/modules/dev" "$HOME/remote"
            git init -q --bare "$HOME/remote/nixos-config.git"
            cd "$repo" && git init -q . && git remote add origin "$HOME/remote/nixos-config.git"
            echo sandbox > modules/dev/pi.nix && echo text > notes.md && echo "{ }" > flake.nix
            git add -A && git commit -q -m base && git push -q -u origin main

            ## Step 2. Gate 2: no commit without a passed check of exactly this content
            echo more >> notes.md && git add -A
            expect "a commit without a check" "$(outcome yes $config guard)" refused
            said "no passed check is recorded"
            expect "the check" "$(outcome yes $config check)" accepted
            expect "the commit after the check" "$(outcome yes $config guard)" accepted
            echo again >> notes.md && git add -A
            expect "a change after the check" "$(outcome yes $config guard)" refused
            echo unstaged >> notes.md
            expect "a check while the folder differs from the staged content" "$(outcome yes $config check)" refused
            said "differs from the staged content"
            git add -A && touch BROKEN && git add -A
            expect "a check that fails" "$(outcome yes $config check)" refused
            expect "a commit after a failed check" "$(outcome yes $config guard)" refused
            git rm -q -f --cached BROKEN && rm BROKEN

            ## Step 3. Gate 1: protected files need a typed yes; ordinary ones do not ask
            expect "an ordinary change, answer no" "$(outcome no $config commit 'ordinary')" accepted
            expect "it was pushed" "$(git -C "$HOME/remote/nixos-config.git" log --format=%s -1)" ordinary
            echo weaker >> modules/dev/pi.nix
            expect "a protected file, answer no" "$(outcome no $config commit 'protected')" refused
            said "modules/dev/pi.nix"
            expect "nothing was committed" "$(git log --format=%s -1)" ordinary
            expect "a protected file, no terminal" "$(CONFIG_GUARD_TTY=/nonexistent $config commit 'protected' > /dev/null 2>&1 && echo accepted || echo refused)" refused
            expect "a protected file, answer yes" "$(outcome yes $config commit 'protected')" accepted
            expect "it was committed" "$(git log --format=%s -1)" protected
            echo "{ }" > modules/extra.nix
            expect "a new module, answer no" "$(outcome no $config commit 'module')" refused
            said "a module added"
            expect "a new module, answer yes" "$(outcome yes $config commit 'module')" accepted
            mkdir -p docs && echo text > docs/new.md
            expect "a new ordinary file, answer no" "$(outcome no $config commit 'docs')" accepted

            ## Step 4. Only the kept repositories
            mkdir -p "$HOME/repos/other" && cd "$HOME/repos/other" && git init -q .
            expect "another repository" "$(outcome yes $config check)" refused
            said "not one of the repositories"

            ## Step 5. A repository of secrets: a file that is not encrypted fails the check
            secrets=$HOME/repos/nixos-secrets
            mkdir -p "$secrets/secrets" && cd "$secrets" && git init -q .
            age-keygen -o "$TMPDIR/key.txt" 2> /dev/null
            echo "value: hidden" > secrets/host.yaml
            sops encrypt --age "$(age-keygen -y "$TMPDIR/key.txt")" --in-place secrets/host.yaml
            git add -A
            expect "encrypted secrets" "$(outcome yes ${tool}/bin/config check)" accepted
            echo "value: readable" > secrets/plain.yaml && git add -A
            expect "a secret that is not encrypted" "$(outcome yes ${tool}/bin/config check)" refused
            said "secrets/plain.yaml is not encrypted"

            ## Step 6. The extension updater, against a stand-in registry
            mkdir -p registry/@scope/one registry/two
            echo '{"version":"2.0.0","dist":{"integrity":"sha512-bmV3SGFzaE9uZQ=="}}' > registry/@scope/one/latest
            echo '{"version":"1.0.0","dist":{"integrity":"sha512-c2FtZUhhc2g="}}' > registry/two/latest
            printf '%s\n' '(npm "@scope/one" "1.5.0"' '  "sha512-b2xkSGFzaA=="' ')' '(npm "two" "1.0.0" "sha512-c2FtZUhhc2g=")' 'other = "1.5.0";' '"@scope/one 1.5.0" "two 1.0.0"' > pins.nix
            CONFIG_NPM_REGISTRY=file://$PWD/registry python3 -I ${../../config-tool/update-extensions.py} pins.nix > updater.out
            cat updater.out
            expect "the updated file" "$(tr '\n' ' ' < pins.nix)" '(npm "@scope/one" "2.0.0"   "sha512-bmV3SGFzaE9uZQ==" ) (npm "two" "1.0.0" "sha512-c2FtZUhhc2g=") other = "1.5.0"; "@scope/one 2.0.0" "two 1.0.0" '
            grep -q '@scope/one: 1.5.0 -> 2.0.0' updater.out && grep -q 'two: unchanged' updater.out || { echo "FAIL: the updater did not say what changed"; failed=1; }
            # An answer that is not a version and a hash, and a package the registry does not know: the file stays as it is
            cp pins.nix before.nix
            echo '{"version":"3.0.0\"; other","dist":{"integrity":"sha512-bmV3SGFzaE9uZQ=="}}' > registry/two/latest
            if CONFIG_NPM_REGISTRY=file://$PWD/registry python3 -I ${../../config-tool/update-extensions.py} pins.nix > /dev/null 2>&1; then echo "FAIL: a malformed answer was accepted"; failed=1; fi
            rm registry/two/latest
            if CONFIG_NPM_REGISTRY=file://$PWD/registry python3 -I ${../../config-tool/update-extensions.py} pins.nix > /dev/null 2>&1; then echo "FAIL: a missing package was accepted"; failed=1; fi
            expect "the file after two refused updates" "$(cmp -s pins.nix before.nix && echo unchanged || echo changed)" unchanged

            [ "$failed" = 0 ] || exit 1
            touch "$out"
          '';
    };
}
