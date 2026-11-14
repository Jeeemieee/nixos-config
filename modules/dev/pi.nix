# The pi coding agent, always run inside a bubblewrap sandbox; users opt in by importing homeManager.pi
# The sandbox sees the project (the nearest folder upwards that holds .git, or the current folder itself; its .git read-only), the Nix store and the network,
# and nothing else of the home folder, no session sockets (Docker, D-Bus, SSH agent, keyrings) and no other processes
# Of ~/.pi/agent it sees the declared files, fixed and read-only, and keeps the login and the sessions; whatever else is written there is discarded at exit
# Its instructions, settings and extensions are declared here and read-only, also for pi itself
{ inputs, ... }:
let
  # The extensions pi loads, by their folder in the tree below
  extensionNames = [
    "@juicesharp/rpiv-todo"
    "@juicesharp/rpiv-ask-user-question"
    "@geminixiang/pi-simplify"
    "@gotgenes/pi-anthropic-auth"
    "pi-chatgpt-limit"
  ];

  # The extensions at fixed versions in one node_modules tree, where the rpiv packages find rpiv-config as their sibling
  # pi itself provides what they import from pi (pi-coding-agent, pi-tui, pi-ai, typebox)
  # To update one: change its version and hash; `npm view <name>@<version> dist.integrity` prints the hash of an npm package
  mkExtensions =
    pkgs:
    let
      npm = name: version: hash: {
        inherit name;
        unpack = "tar -xzf ${
          pkgs.fetchurl {
            url = "https://registry.npmjs.org/${name}/-/${baseNameOf name}-${version}.tgz";
            inherit hash;
          }
        } --strip-components=1 -C";
      };
      packages = [
        (npm "@juicesharp/rpiv-todo" "2.15.0"
          "sha512-8WfYssdgQgSWzFNsRzdw5Z6ZJIjO2ecM/YqEzYpR/ore+Hh5aNmafGVy94uFbIofAv2wGGitx5e3J/ucRrViXQ=="
        )
        (npm "@juicesharp/rpiv-ask-user-question" "2.15.0"
          "sha512-Gm6de5IZF52BaSeh9dnDqJBn821Z5XfJkCmhkCmqTzvNv3SCpSv1mA4Gj5VBcfrSe+xTtWSVQzJwIqJFQHH3Lg=="
        )
        # Not an extension: the dependency of the two rpiv extensions
        (npm "@juicesharp/rpiv-config" "2.15.0"
          "sha512-S2BAGX4dJjQ2AyNYOEjC6ha04p9f6CdEfmtxpdxzSKrfDMwqIvOjjO9HiHc1IPY7jDY1q2Q8cGCtpIZWV6Y8NQ=="
        )
        (npm "@geminixiang/pi-simplify" "0.2.0"
          "sha512-pASkAwxqwU7vB8phjir1h50jSaSwaziro/R3FbKC+GMtNdFNDVybTe1VQ0gcKQ5l6fVoxm5NhyZ30XUdKqM68g=="
        )
        (
          npm "@gotgenes/pi-anthropic-auth" "3.4.4"
            "sha512-oWCkPFSa7AkvSju3OrlYu0GTo8Jdqz2OvszJtHj0hzXLw8tErtmPPMYPqK2it3zaXu+Wl2oH8nfpeIUVsqW2Vw=="
          // {
            # pi names an extension after the folder of its entry file, here "src": an entry in the package folder gives it its own name
            fix = ''
              echo 'export { default } from "./src/index.ts";' > index.ts
              jq '.pi.extensions = [ "./index.ts" ]' package.json > package.json.new
              mv package.json.new package.json
            '';
          }
        )
        {
          # Version 0.3.1, not published on npm
          name = "pi-chatgpt-limit";
          unpack = "cp -r ${
            pkgs.fetchFromGitHub {
              owner = "patlux";
              repo = "pi-chatgpt-limit";
              rev = "cff2c8da7b37e154d9f2776527be1e4ceeadf8fc";
              hash = "sha256-rsD5jOYatgxtACDIQTRa5+BJWIWnaI3uYo5DcZ112+s=";
            }
          }/. -t";
        }
      ];
    in
    pkgs.runCommand "pi-extensions" { nativeBuildInputs = [ pkgs.jq ]; } (
      pkgs.lib.concatMapStrings (package: ''
        mkdir -p "$out/node_modules/${package.name}"
        ${package.unpack} "$out/node_modules/${package.name}"
        chmod -R u+w "$out/node_modules/${package.name}"
        (cd "$out/node_modules/${package.name}" && ${package.fix or ":"})
      '') packages
    );

  # ~/.pi/agent/settings.json; pi cannot change it, so /settings and `pi install` do not persist
  settingsFor = extensions: {
    theme = "dark";
    defaultProvider = "openai-codex";
    defaultModel = "gpt-5.6-sol";
    defaultThinkingLevel = "high";
    # Extensions, settings and prompts that a project brings in its .pi folder are not loaded, and pi does not ask:
    # an agent can write that folder, and a habitual "yes" would run its code in every later session; `pi --approve` loads them once
    defaultProjectTrust = "never";
    packages = map (name: "${extensions}/node_modules/${name}") extensionNames;
  };

  # Build a sandboxed launcher; the checks reuse it with a probe instead of pi
  mkSandbox =
    pkgs:
    {
      name,
      command,
      environment ? { },
      # Files below the home folder that Home Manager declares, as links into the Nix store
      declared ? [ ],
      # Repositories below ~/repos with files that decide what an agent may do: { <repository> = [ <path in it> ... ]; }
      # They are read-only in the sandbox unless it is started with --unlock
      protected ? { },
    }:
    let
      # The sandbox has no desktop session, so the system's xdg-open (kde-open) crashes there; this one fails quietly instead
      # pi shows login links itself and treats opening the browser as best effort: Ctrl+click the link in the terminal
      noBrowser = pkgs.writeTextFile {
        name = "pi-sandbox-no-browser";
        destination = "/bin/xdg-open";
        executable = true;
        text = ''
          #!${pkgs.runtimeShell}
          exit 1
        '';
      };
    in
    pkgs.writeShellApplication {
      inherit name;
      runtimeInputs = with pkgs; [
        bubblewrap
        coreutils
        git
      ];
      text = ''
        deny() {
          echo "${name}: $1" >&2
          exit 2
        }

        # A path may only be given to the sandbox if it is a normal folder in the home folder, or on /tmp or removable or mounted data drives
        # The home folder itself, its parents, and hidden folders in it (configuration, keys, browser profiles) are refused
        checkPath() {
          local path=$1
          case "$path/" in
            "$HOME"/.*) deny "refusing $path: hidden folders in your home hold configuration and keys" ;;
            "$HOME"/?*) return 0 ;;
            /tmp/?* | /mnt/?* | /media/?* | /srv/?* | /run/media/"$USER"/?*) return 0 ;;
          esac
          case "$HOME/" in
            "$path"/*) deny "refusing $path: it contains your whole home folder; start ${name} inside a project" ;;
          esac
          deny "refusing $path: only folders in your home, /tmp, /mnt, /media, /srv or /run/media/$USER can be shared"
        }

        # The wrapper's own options come first; everything else goes to ${name}
        extraBinds=()
        unlock=0
        while [ "$#" -gt 0 ]; do
          case "$1" in
            --unlock)
              unlock=1
              shift
              ;;
            --allow | --allow-ro)
              [ "$#" -ge 2 ] || deny "$1 needs a folder"
              allowed=$(realpath -e -- "$2") || deny "$1: $2 does not exist"
              checkPath "$allowed"
              if [ "$1" = --allow ]; then extraBinds+=(--bind "$allowed" "$allowed"); else extraBinds+=(--ro-bind "$allowed" "$allowed"); fi
              shift 2
              ;;
            *) break ;;
          esac
        done

        # The project is the nearest folder upwards that holds .git, or the current folder itself
        # Found by path alone: git would answer from the repository's own settings (core.worktree), which an earlier session could have changed
        workdir=$(pwd -P)
        project=$workdir
        folder=$workdir
        while [ "$folder" != / ]; do
          if [ -e "$folder/.git" ] || [ -L "$folder/.git" ]; then
            project=$folder
            break
          fi
          folder=$(dirname "$folder")
        done
        checkPath "$project"

        # The whole of .git is read-only in the sandbox: git's settings and hooks run programs when the user next uses git outside it
        # As a mount it can also not be renamed, removed or replaced by another .git. Reading works (status, log, diff); staging and committing do not
        protect=()
        if [ -L "$project/.git" ]; then
          deny "refusing $project: its .git is a link, which cannot be protected; start ${name} in the repository it points to"
        elif [ -e "$project/.git" ]; then
          protect+=(--ro-bind "$project/.git" "$project/.git")
        fi

        # Files that decide what an agent may do (the sandbox itself, the checks, secrets, disk, installer, version pins) are read-only as well
        # As mounts they can neither be changed nor renamed, removed or replaced. --unlock leaves them writable for this one session
        protectedPaths=()
        ${pkgs.lib.concatStrings (
          pkgs.lib.mapAttrsToList (repository: paths: ''
            if [ "$project" = "$HOME/repos/"${pkgs.lib.escapeShellArg repository} ]; then
              protectedPaths=(${pkgs.lib.escapeShellArgs paths})
            fi
          '') protected
        )}
        if [ "$unlock" = 1 ]; then
          if [ "''${#protectedPaths[@]}" -gt 0 ]; then
            echo "${name}: unlocked for this session: the protected files of $project can be changed (''${protectedPaths[*]})" >&2
          else
            deny "--unlock: $project has no protected files"
          fi
        else
          for path in "''${protectedPaths[@]}"; do
            if [ -L "$project/$path" ]; then
              deny "refusing $project: its protected $path is a link, which cannot be protected"
            elif [ -e "$project/$path" ]; then
              protect+=(--ro-bind "$project/$path" "$project/$path")
            fi
          done
          # pi reads this file instead of the repository's AGENTS.md when it exists; it cannot be protected before it exists
          if [ "''${#protectedPaths[@]}" -gt 0 ] && [ -e "$project/AGENTS.override.md" ]; then
            deny "refusing $project: it holds an AGENTS.override.md, which would replace the repository's instructions; remove it, or start with --unlock to work on it"
          fi
        fi

        # ~/.pi/agent inside the sandbox is a folder in memory. It holds the declared files as read-only mounts, which cannot be
        # deleted or replaced, and two things that persist: the sessions, and the login in its own folder. pi locks the login
        # file next to its real location, so several sandboxes share that lock through the login folder
        # Anything else written there (an extension, a system prompt, model endpoints, the model cache) is gone at exit
        agent=$HOME/.pi/agent
        mkdir -p "$agent/sessions" "$agent/login"
        chmod 700 "$agent/login"
        # A login file from pi running without this sandbox moves to its new place once
        if [ -f "$agent/auth.json" ] && [ ! -L "$agent/auth.json" ] && [ ! -e "$agent/login/auth.json" ]; then
          mv "$agent/auth.json" "$agent/login/auth.json"
        fi
        # What pi itself writes when the file is missing
        if [ ! -e "$agent/login/auth.json" ]; then
          (umask 077 && printf '{}' > "$agent/login/auth.json")
        fi

        declared=(${toString (map pkgs.lib.escapeShellArg declared)})
        declaredBinds=()
        for path in "''${declared[@]}"; do
          target=$(realpath -e -- "$HOME/$path" 2> /dev/null) || target=
          case "$target" in
            /nix/store/*) ;;
            *) deny "$HOME/$path is not the declared file (a link into the Nix store); restore it with: systemctl restart home-manager-$USER.service" ;;
          esac
          [ -L "$HOME/$path" ] || deny "$HOME/$path is not the declared file (a link into the Nix store); restore it with: systemctl restart home-manager-$USER.service"
          declaredBinds+=(--ro-bind "$target" "$HOME/$path")
        done

        exec bwrap \
          --unshare-all --unshare-user --share-net --die-with-parent \
          --disable-userns \
          --ro-bind /nix/store /nix/store \
          --bind-try /nix/var/nix/daemon-socket /nix/var/nix/daemon-socket \
          --ro-bind /etc /etc \
          --ro-bind-try /bin /bin \
          --ro-bind-try /usr /usr \
          --proc /proc \
          --dev /dev \
          --tmpfs /tmp \
          --tmpfs /run \
          --ro-bind-try /run/current-system /run/current-system \
          --ro-bind-try /run/opengl-driver /run/opengl-driver \
          --tmpfs "$HOME" \
          --dir "$agent" \
          "''${declaredBinds[@]}" \
          --bind "$agent/login" "$agent/login" \
          --symlink login/auth.json "$agent/auth.json" \
          --bind "$agent/sessions" "$agent/sessions" \
          --ro-bind-try "$HOME/.config/git" "$HOME/.config/git" \
          --bind "$project" "$project" \
          "''${protect[@]}" \
          "''${extraBinds[@]}" \
          --chdir "$workdir" \
          --unsetenv SSH_AUTH_SOCK \
          --unsetenv DBUS_SESSION_BUS_ADDRESS \
          --unsetenv DOCKER_HOST \
          --unsetenv XDG_RUNTIME_DIR \
          --unsetenv WAYLAND_DISPLAY \
          --unsetenv DISPLAY \
          --setenv PATH "${noBrowser}/bin:$PATH" \
          ${
            pkgs.lib.concatStringsSep " " (
              pkgs.lib.mapAttrsToList (key: value: "--setenv ${key} ${pkgs.lib.escapeShellArg value}") environment
            )
          } \
          -- ${command} "$@"
      '';
    };
in
{
  flake.modules.homeManager.pi =
    { config, pkgs, ... }:
    let
      # Nix owns pi's version; `pi update` explains that instead of installing over the store
      noSelfUpdate = pkgs.writeShellScript "pi-no-self-update" ''
        echo "pi is managed by Nix: update it with 'nix flake update nixpkgs-pi' in ~/repos/nixos-config and rebuild" >&2
        exit 1
      '';
    in
    {
      home.packages = [
        (mkSandbox pkgs {
          name = "pi";
          command = "${pkgs.pi-coding-agent}/bin/pi";
          environment = {
            PI_SKIP_VERSION_CHECK = "1";
            PI_SELF_UPDATE_COMMAND = "${noSelfUpdate}";
          };
          # Every file this configuration puts into pi's folder
          declared = builtins.filter (pkgs.lib.hasPrefix ".pi/agent/") (builtins.attrNames config.home.file);
          # The configuration's own repositories: what decides an agent's limits is read-only for agents
          protected = import ../../config-tool/protected.nix;
        })
      ];

      # Without this, a nixos-secrets pin from before the file existed gives a dangling link, and pi starts without instructions
      assertions = [
        {
          assertion = builtins.pathExists "${inputs.nixos-secrets}/pi/AGENTS.md";
          message = "homeManager.pi needs pi/AGENTS.md in the nixos-secrets input: update its pin with 'nix flake update nixos-secrets'";
        }
      ];

      # Links into the Nix store: read-only for everyone. The sandbox mounts them in place, so they cannot be removed or replaced there either
      # They replace files of the same name, which pi or a copied ~/.pi leaves behind; Home Manager would otherwise abort
      home.file = {
        # The user's instructions for every agent; private, so from nixos-secrets (plain, not encrypted)
        ".pi/agent/AGENTS.md" = {
          source = "${inputs.nixos-secrets}/pi/AGENTS.md";
          force = true;
        };
        ".pi/agent/settings.json" = {
          text = builtins.toJSON (settingsFor (mkExtensions pkgs));
          force = true;
        };
        # Display settings of the pi-chatgpt-limit extension
        ".pi/agent/chatgpt-limit.json" = {
          text = builtins.toJSON {
            quotaWindow = "both";
            displayMode = "compact";
          };
          force = true;
        };
      };
    };

  perSystem =
    { pkgs, ... }:
    let
      # Runs inside the sandbox and reports what it can reach; the check below compares it with the expected answers
      probe = pkgs.writeShellScript "pi-sandbox-probe" ''
        report() { echo "$1=$2"; }
        if [ -e "$HOME/.ssh/id_test" ]; then report ssh visible; else report ssh hidden; fi
        if [ -e "$HOME/.bitwarden-ssh-agent.sock" ]; then report bitwarden-agent visible; else report bitwarden-agent hidden; fi
        if [ -e "$HOME/.config/restic/password" ]; then report restic visible; else report restic hidden; fi
        if [ -e "$HOME/other-project/file" ]; then report other visible; else report other hidden; fi
        if echo ok > "$PWD/written-inside"; then report project writable; else report project readonly; fi
        echo leak > "$HOME/leaked" 2>/dev/null || true
        if echo hook >> "$PROJECT/.git/hooks/post-checkout" 2>/dev/null; then report hooks writable; else report hooks readonly; fi
        if [ -e "$HOME/.pi/agent/undeclared.md" ]; then report undeclared-pi-file visible; else report undeclared-pi-file hidden; fi
        if [ -e "$HOME/data/allowed" ]; then report allowed visible; else report allowed hidden; fi
        if [ -n "''${SSH_AUTH_SOCK:-}" ]; then report ssh-agent set; else report ssh-agent unset; fi
        report pid1 "$(cat /proc/1/comm)"
        report version-check "''${PI_SKIP_VERSION_CHECK:-unset}"
        # A nested user namespace would let a process stack its own mounts over the declared files, for itself and its children
        if ${pkgs.util-linux}/bin/unshare --user --map-root-user --mount true 2>/dev/null; then report nested-namespaces allowed; else report nested-namespaces refused; fi
        if [ "$(cat "$HOME/.pi/agent/AGENTS.md" 2>/dev/null)" != rules ]; then report instructions unreadable
        elif echo more >> "$HOME/.pi/agent/AGENTS.md" 2>/dev/null; then report instructions writable
        else report instructions readonly; fi
        # Deleting the declared file and writing another one in its place
        rm -f "$HOME/.pi/agent/AGENTS.md" 2>/dev/null
        echo evil > "$HOME/.pi/agent/AGENTS.md" 2>/dev/null
        mv "$HOME/.pi/agent/sessions" "$HOME/.pi/agent/moved" 2>/dev/null
        if [ "$(cat "$HOME/.pi/agent/AGENTS.md" 2>/dev/null)" = rules ]; then report instructions-replaced no; else report instructions-replaced yes; fi
        # What pi keeps between runs, and what an agent might try to leave behind
        echo session > "$HOME/.pi/agent/sessions/probe-session" && report sessions writable
        report login "$(readlink "$HOME/.pi/agent/auth.json")=$(cat "$HOME/.pi/agent/auth.json")"
        echo '{"probe":true}' > "$HOME/.pi/agent/auth.json"
        mkdir -p "$HOME/.pi/agent/extensions" && echo evil > "$HOME/.pi/agent/extensions/evil.ts" && echo evil > "$HOME/.pi/agent/SYSTEM.md" \
          && echo evil > "$HOME/.pi/agent/models-store.json" && report undeclared-write accepted
        case "$(command -v xdg-open)" in
          *-pi-sandbox-no-browser/bin/xdg-open) if xdg-open https://example.org; then report opener opened; else report opener quiet-failure; fi ;;
          *) report opener system ;;
        esac
      '';
      sandboxedProbe = mkSandbox pkgs {
        name = "pi";
        command = "${probe}";
        environment.PI_SKIP_VERSION_CHECK = "1";
        declared = [ ".pi/agent/AGENTS.md" ];
      };
      extensions = mkExtensions pkgs;
      settingsFile = pkgs.writeText "pi-settings.json" (builtins.toJSON (settingsFor extensions));
    in
    {
      # The sandbox must expose the project and ~/.pi, and hide the rest of the home, session sockets and host processes
      checks.pi-sandbox =
        pkgs.runCommand "pi-sandbox-check"
          {
            nativeBuildInputs = [
              pkgs.git
              pkgs.bubblewrap
            ];
          }
          ''
            export HOME=$TMPDIR/home USER=tester SSH_AUTH_SOCK=/run/user/1000/ssh-agent
            mkdir -p "$HOME/.ssh" "$HOME/.config/restic" "$HOME/.pi" "$HOME/other-project" "$HOME/project" "$HOME/data"
            touch "$HOME/.ssh/id_test" "$HOME/.config/restic/password" "$HOME/other-project/file" "$HOME/data/allowed"
            # Stands in for the socket of Bitwarden's SSH agent, which holds the key for GitHub
            touch "$HOME/.bitwarden-ssh-agent.sock"
            # Declared files are links into the store, as Home Manager creates them
            mkdir -p "$HOME/.pi/agent"
            ln -s ${pkgs.writeText "pi-sandbox-rules" "rules"} "$HOME/.pi/agent/AGENTS.md"
            # A file in pi's folder that is not declared, and a login file from pi running without the sandbox
            echo undeclared > "$HOME/.pi/agent/undeclared.md"
            printf '{"old":true}' > "$HOME/.pi/agent/auth.json"
            git -C "$HOME/project" init -q
            touch "$HOME/project/.git/hooks/post-checkout"
            mkdir -p "$HOME/project/sub"

            # Control for nested-namespaces=refused below: outside the sandbox the same command succeeds
            ${pkgs.util-linux}/bin/unshare --user --map-root-user --mount true || { echo "FAIL: user namespaces are unavailable here, so the sandbox's refusal proves nothing"; exit 1; }

            # Normal use from a subfolder of the project, with one extra folder allowed read-only
            (cd "$HOME/project/sub" && PROJECT=$HOME/project ${sandboxedProbe}/bin/pi --allow-ro "$HOME/data") > actual
            cat > expected <<EOF
            ssh=hidden
            bitwarden-agent=hidden
            restic=hidden
            other=hidden
            project=writable
            hooks=readonly
            undeclared-pi-file=hidden
            allowed=visible
            ssh-agent=unset
            pid1=bwrap
            version-check=1
            nested-namespaces=refused
            instructions=readonly
            instructions-replaced=no
            sessions=writable
            login=login/auth.json={"old":true}
            undeclared-write=accepted
            opener=quiet-failure
            EOF
            sed -i 's/^ *//' expected
            diff expected actual
            [ -e "$HOME/project/sub/written-inside" ] || { echo "FAIL: project write did not reach the host"; exit 1; }
            [ ! -e "$HOME/leaked" ] || { echo "FAIL: a write to the sandbox home reached the real home"; exit 1; }
            [ ! -s "$HOME/project/.git/hooks/post-checkout" ] || { echo "FAIL: the sandbox changed a git hook"; exit 1; }

            # After the run, on the host: the declared file is untouched, the sessions and the login persist, nothing else was left behind
            agent=$HOME/.pi/agent
            [ -L "$agent/AGENTS.md" ] && [ "$(cat "$agent/AGENTS.md")" = rules ] || { echo "FAIL: the declared file changed on the host"; exit 1; }
            [ "$(cat "$agent/sessions/probe-session")" = session ] || { echo "FAIL: the session did not persist"; exit 1; }
            [ ! -e "$agent/auth.json" ] && [ "$(cat "$agent/login/auth.json")" = '{"probe":true}' ] || { echo "FAIL: the login did not move or persist"; exit 1; }
            [ "$(stat -c %a "$agent/login")" = 700 ] || { echo "FAIL: the login folder is not private"; exit 1; }
            ls -A "$agent" | sort | tr '\n' ' ' > left
            [ "$(cat left)" = "AGENTS.md login sessions undeclared.md " ] || { echo "FAIL: left behind in pi's folder: $(cat left)"; exit 1; }

            # Refusals: the home folder, hidden folders and system paths are never shared
            refuse() {
              local label=$1; shift
              if "$@" > out 2>&1; then echo "FAIL ($label): not refused"; cat out; exit 1; fi
              grep -q "refusing" out || { echo "FAIL ($label): no descriptive refusal"; cat out; exit 1; }
              echo "refused ($label): $(cat out)"
            }
            refuse home bash -c 'cd "$HOME" && ${sandboxedProbe}/bin/pi'
            refuse hidden bash -c 'cd "$HOME/.config" && ${sandboxedProbe}/bin/pi'
            refuse allow-home bash -c 'cd "$HOME/project" && ${sandboxedProbe}/bin/pi --allow "$HOME"'
            refuse allow-system bash -c 'cd "$HOME/project" && ${sandboxedProbe}/bin/pi --allow /etc'
            refuse allow-ssh bash -c 'cd "$HOME/project" && ${sandboxedProbe}/bin/pi --allow-ro "$HOME/.ssh"'

            # A declared file that was replaced by a normal file outside the sandbox: refuse instead of starting without it
            rm "$agent/AGENTS.md" && echo replaced > "$agent/AGENTS.md"
            if (cd "$HOME/project" && ${sandboxedProbe}/bin/pi) > out 2>&1; then echo "FAIL (replaced declared file): not refused"; exit 1; fi
            grep -q "is not the declared file" out || { echo "FAIL (replaced declared file): no descriptive refusal"; cat out; exit 1; }
            echo "refused (replaced declared file): $(cat out)"
            touch "$out"
          '';

      # What a sandbox can change in git, and what the launcher takes from git when it starts
      # Two weaknesses that were found in an earlier version, each with a control showing that the test can detect it
      checks.pi-sandbox-git =
        let
          gitProbe = pkgs.writeShellScript "pi-sandbox-git-probe" ''
            report() { echo "$1=$2"; }
            cd "$PROJECT"
            if [ -n "''${SIBLING:-}" ]; then
              # Started in a project whose git settings name the folder above it as its work tree
              if [ -e "$SIBLING" ]; then report sibling visible; else report sibling hidden; fi
              if echo x >> "$SIBLING" 2>/dev/null; then report sibling-write accepted; else report sibling-write refused; fi
              exit 0
            fi
            # Reading git works
            if git status --porcelain > /dev/null 2>&1; then report git-status works; else report git-status fails; fi
            if [ "$(git log --format=%s -1 2>/dev/null)" = base ]; then report git-log works; else report git-log fails; fi
            if echo change >> tracked && [ -n "$(git diff --stat 2>/dev/null)" ]; then report git-diff works; else report git-diff fails; fi
            # A program that git would run when the user next uses git here, outside the sandbox
            printf '#!/bin/sh\necho ran > %s\n' "$MARKER" > "$PROJECT/left-behind.sh" && chmod +x "$PROJECT/left-behind.sh"
            if git config core.fsmonitor "$PROJECT/left-behind.sh" 2>/dev/null; then report git-config-write accepted; else report git-config-write refused; fi
            if git add left-behind.sh 2>/dev/null; then report git-add accepted; else report git-add refused; fi
            # The same through a new .git in place of the old one
            if mv .git .git-away 2>/dev/null && git init -q . 2>/dev/null && git config core.fsmonitor "$PROJECT/left-behind.sh" 2>/dev/null; then
              report git-dir-replace done
            else
              report git-dir-replace refused
              if rm -rf .git 2>/dev/null; then report git-dir-remove done; else report git-dir-remove refused; fi
              if echo "$PROJECT/elsewhere" > .git/commondir 2>/dev/null; then report git-commondir written; else report git-commondir refused; fi
            fi
          '';
          sandboxedGitProbe = mkSandbox pkgs {
            name = "pi";
            command = "${gitProbe}";
            declared = [ ".pi/agent/AGENTS.md" ];
          };
        in
        pkgs.runCommand "pi-sandbox-git-check"
          {
            nativeBuildInputs = [
              pkgs.git
              pkgs.bubblewrap
            ];
          }
          ''
            export HOME=$TMPDIR/home USER=tester GIT_CONFIG_GLOBAL=/dev/null
            export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.org GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.org
            mkdir -p "$HOME/.pi/agent" "$HOME/group/project" "$HOME/group/sibling" "$HOME/work/project"
            ln -s ${pkgs.writeText "pi-sandbox-rules" "rules"} "$HOME/.pi/agent/AGENTS.md"
            failed=0
            expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; failed=1; fi; }

            ## Step 1. Control: a program named in a repository's settings runs at the next `git status`
            git init -q "$HOME/control" && git -C "$HOME/control" commit -q --allow-empty -m base
            printf '#!/bin/sh\necho ran > %s\n' "$HOME/control-marker" > "$HOME/control/left-behind.sh" && chmod +x "$HOME/control/left-behind.sh"
            git -C "$HOME/control" config core.fsmonitor "$HOME/control/left-behind.sh"
            git -C "$HOME/control" status > /dev/null 2>&1 || true
            expect "control: a program named in the settings runs at git status" "$([ -e "$HOME/control-marker" ] && echo ran || echo not-run)" ran

            ## Step 2. From inside the sandbox: reading git works, changing it does not
            project=$HOME/work/project
            git init -q "$project" && echo content > "$project/tracked" && git -C "$project" add tracked && git -C "$project" commit -q -m base
            before=$(cd "$project/.git" && find . -type f | sort | xargs sha256sum | sha256sum)
            (cd "$project" && PROJECT=$project MARKER=$HOME/marker-outside ${sandboxedGitProbe}/bin/pi) > actual
            cat actual
            expect "inside: git status" "$(grep -x 'git-status=.*' actual)" "git-status=works"
            expect "inside: git log" "$(grep -x 'git-log=.*' actual)" "git-log=works"
            expect "inside: git diff" "$(grep -x 'git-diff=.*' actual)" "git-diff=works"
            expect "inside: writing the repository's settings" "$(grep -x 'git-config-write=.*' actual)" "git-config-write=refused"
            expect "inside: staging a file" "$(grep -x 'git-add=.*' actual)" "git-add=refused"
            expect "inside: replacing .git" "$(grep -x 'git-dir-replace=.*' actual)" "git-dir-replace=refused"
            expect "inside: removing .git" "$(grep -x 'git-dir-remove=.*' actual || echo not-tried)" "git-dir-remove=refused"
            expect "inside: a commondir file" "$(grep -x 'git-commondir=.*' actual || echo not-tried)" "git-commondir=refused"
            # The user's next git command in that project, outside the sandbox
            git -C "$project" status > /dev/null 2>&1 || true
            expect "outside: the program at the user's git status" "$([ -e "$HOME/marker-outside" ] && echo ran || echo not-run)" not-run
            after=$(cd "$project/.git" 2>/dev/null && find . -type f | sort | xargs sha256sum | sha256sum)
            expect "outside: .git is unchanged" "$([ "$before" = "$after" ] && echo unchanged || echo changed)" unchanged
            expect "outside: the agent's change to a tracked file arrived" "$(tail -n 1 "$project/tracked")" change

            ## Step 3. A project whose git settings name the folder above it as its work tree
            project=$HOME/group/project
            git init -q "$project" && git -C "$project" commit -q --allow-empty -m base
            echo private > "$HOME/group/sibling/file"
            git -C "$project" config core.worktree "$HOME/group"
            expect "control: git names the folder above as the project" "$(git -C "$project" rev-parse --show-toplevel)" "$HOME/group"
            (cd "$project" && PROJECT=$project SIBLING=$HOME/group/sibling/file ${sandboxedGitProbe}/bin/pi) > actual
            cat actual
            expect "inside: the folder beside the project" "$(grep -x 'sibling=.*' actual)" "sibling=hidden"
            expect "inside: writing beside the project" "$(grep -x 'sibling-write=.*' actual)" "sibling-write=refused"
            expect "outside: the file beside the project" "$(cat "$HOME/group/sibling/file")" private

            [ "$failed" = 0 ] || { echo "pi-sandbox-git: git is not protected as expected"; exit 1; }
            touch "$out"
          '';

      # Protected files of a repository are read-only in the sandbox, as mounts; --unlock leaves them writable for one session
      checks.pi-sandbox-protected =
        let
          protectedProbe = pkgs.writeShellScript "pi-sandbox-protected-probe" ''
            report() { echo "$1=$2"; }
            cd "$PROJECT"
            if echo change >> guarded/file 2>/dev/null; then report file-change accepted; else report file-change refused; fi
            if echo new > guarded/new 2>/dev/null; then report folder-new-file accepted; else report folder-new-file refused; fi
            if mv guarded guarded-away 2>/dev/null; then report folder-rename accepted; else report folder-rename refused; fi
            if echo change >> single 2>/dev/null; then report single-change accepted; else report single-change refused; fi
            if rm -f single 2>/dev/null && [ ! -e single ]; then report single-remove accepted; else report single-remove refused; fi
            if echo replaced > single.new 2>/dev/null && mv single.new single 2>/dev/null; then report single-replace accepted; else report single-replace refused; fi
            if echo change >> ordinary 2>/dev/null; then report ordinary-change accepted; else report ordinary-change refused; fi
          '';
          sandboxedProtectedProbe = mkSandbox pkgs {
            name = "pi";
            command = "${protectedProbe}";
            declared = [ ".pi/agent/AGENTS.md" ];
            protected.guarded-repo = [
              "guarded"
              "single"
              "not-there"
            ];
          };
        in
        pkgs.runCommand "pi-sandbox-protected-check" { nativeBuildInputs = [ pkgs.bubblewrap ]; } ''
          export HOME=$TMPDIR/home USER=tester
          mkdir -p "$HOME/.pi/agent"
          ln -s ${pkgs.writeText "pi-sandbox-rules" "rules"} "$HOME/.pi/agent/AGENTS.md"
          failed=0
          expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; failed=1; fi; }
          fresh() {
            rm -rf "$1" && mkdir -p "$1/guarded"
            echo content > "$1/guarded/file" && echo content > "$1/single" && echo content > "$1/ordinary"
          }
          state() { (cd "$1" && cat guarded/file single ordinary 2> /dev/null | tr '\n' ' '; ls -A | tr '\n' ' '); }

          ## Step 1. A session in the repository, without --unlock: the protected files hold, an ordinary file can be changed
          project=$HOME/repos/guarded-repo
          fresh "$project"
          (cd "$project" && PROJECT=$project ${sandboxedProtectedProbe}/bin/pi) > actual
          cat actual
          for probe in file-change folder-new-file folder-rename single-change single-remove single-replace; do
            expect "protected, $probe" "$(grep -x "$probe=.*" actual)" "$probe=refused"
          done
          expect "an ordinary file" "$(grep -x 'ordinary-change=.*' actual)" "ordinary-change=accepted"
          # single.new is the probe's own ordinary file, left over from its refused attempt to put it in place of the protected one
          expect "afterwards, on the host" "$(state "$project")" "content content content change guarded ordinary single single.new "

          ## Step 2. Control: the same session with --unlock can change them
          fresh "$project"
          (cd "$project" && PROJECT=$project ${sandboxedProtectedProbe}/bin/pi --unlock) > actual 2> message
          cat actual message
          for probe in file-change folder-new-file folder-rename single-change single-remove single-replace; do
            expect "unlocked, $probe" "$(grep -x "$probe=.*" actual)" "$probe=accepted"
          done
          grep -q "unlocked for this session" message || { echo "FAIL: --unlock did not say what it unlocked"; failed=1; }

          ## Step 3. Control: the same folder under another name is no protected repository, and --unlock is refused there
          other=$HOME/repos/another-repo
          fresh "$other"
          (cd "$other" && PROJECT=$other ${sandboxedProtectedProbe}/bin/pi) > actual
          expect "another repository, file-change" "$(grep -x 'file-change=.*' actual)" "file-change=accepted"
          if (cd "$other" && PROJECT=$other ${sandboxedProtectedProbe}/bin/pi --unlock) > out 2>&1; then echo "FAIL: --unlock was accepted where nothing is protected"; failed=1; fi
          grep -q "has no protected files" out || { echo "FAIL: no descriptive refusal of --unlock"; cat out; failed=1; }

          ## Step 4. A file that would replace the repository's instructions, and a protected path that is a link, are refused
          fresh "$project" && echo other-rules > "$project/AGENTS.override.md"
          if (cd "$project" && PROJECT=$project ${sandboxedProtectedProbe}/bin/pi) > out 2>&1; then echo "FAIL: started with an AGENTS.override.md"; failed=1; fi
          grep -q "AGENTS.override.md" out || { echo "FAIL: no descriptive refusal of the override file"; cat out; failed=1; }
          fresh "$project" && rm "$project/single" && ln -s ordinary "$project/single"
          if (cd "$project" && PROJECT=$project ${sandboxedProtectedProbe}/bin/pi) > out 2>&1; then echo "FAIL: started with a protected path that is a link"; failed=1; fi
          grep -q "is a link" out || { echo "FAIL: no descriptive refusal of the link"; cat out; failed=1; }

          [ "$failed" = 0 ] || exit 1
          touch "$out"
        '';

      # The declared extensions and settings: fixed versions, complete, and accepted by pi without the network
      checks.pi-config =
        pkgs.runCommand "pi-config-check"
          {
            nativeBuildInputs = [
              pkgs.jq
              pkgs.nodejs
              pkgs.pi-coding-agent
            ];
          }
          ''
            extensions=${extensions}
            modules=$extensions/node_modules

            # 1. Exactly these packages, at these versions
            find "$modules" -name package.json -not -path '*/node_modules/*/node_modules/*' -maxdepth 3 \
              -exec jq -r '"\(.name) \(.version)"' {} + | sort > actual
            printf '%s\n' \
              "@geminixiang/pi-simplify 0.2.0" \
              "@gotgenes/pi-anthropic-auth 3.4.4" \
              "@juicesharp/rpiv-ask-user-question 2.15.0" \
              "@juicesharp/rpiv-config 2.15.0" \
              "@juicesharp/rpiv-todo 2.15.0" \
              "pi-chatgpt-limit 0.3.1" | sort > expected
            diff expected actual

            # 2. Every extension's entry files exist
            for name in ${toString extensionNames}; do
              for entry in $(jq -r '.pi.extensions[]' "$modules/$name/package.json"); do
                [ -e "$modules/$name/$entry" ] || { echo "FAIL: $name has no $entry"; exit 1; }
              done
            done

            # 3. The rpiv extensions find rpiv-config inside this tree
            for name in rpiv-todo rpiv-ask-user-question; do
              # Resolved as the extensions import it; the package does not export its package.json
              resolved=$(cd "$modules/@juicesharp/$name" && node --input-type=module -e 'console.log(import.meta.resolve("@juicesharp/rpiv-config"))')
              case "$resolved" in
                "file://$modules/@juicesharp/rpiv-config/"*) echo "$name -> $resolved" ;;
                *) echo "FAIL: $name resolves rpiv-config to $resolved"; exit 1 ;;
              esac
            done

            # 4. The settings are exactly the declared ones
            jq -S . ${settingsFile} > settings.actual
            jq -S . > settings.expected <<EOF
            {
              "theme": "dark",
              "defaultProvider": "openai-codex",
              "defaultModel": "gpt-5.6-sol",
              "defaultThinkingLevel": "high",
              "defaultProjectTrust": "never",
              "packages": [
                "$modules/@juicesharp/rpiv-todo",
                "$modules/@juicesharp/rpiv-ask-user-question",
                "$modules/@geminixiang/pi-simplify",
                "$modules/@gotgenes/pi-anthropic-auth",
                "$modules/pi-chatgpt-limit"
              ]
            }
            EOF
            diff settings.expected settings.actual

            # 5. pi, offline, with only the read-only settings in its folder: lists the five extensions and writes nothing
            export HOME=$TMPDIR/home PI_CODING_AGENT_DIR=$TMPDIR/home/.pi/agent PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0
            mkdir -p "$PI_CODING_AGENT_DIR" "$HOME/work"
            ln -s ${settingsFile} "$PI_CODING_AGENT_DIR/settings.json"
            (cd "$HOME/work" && pi list) > list
            cat list
            grep -E '^  /' list | sed 's/^ *//' | sort > listed
            jq -r '.packages[]' ${settingsFile} | sort > declared
            diff declared listed
            [ "$(ls -A "$PI_CODING_AGENT_DIR")" = settings.json ] || { echo "FAIL: pi changed its folder:"; ls -la "$PI_CODING_AGENT_DIR"; exit 1; }

            # 6. pi loads the extensions without a login: it exits with an error when one fails to load, and lists their commands
            (cd "$HOME/work" && echo '{"id": "1", "type": "get_commands"}' | pi --mode rpc --no-session) > commands
            for command in todos simplify code-smell chatgpt-limit anthropic-auth:status; do
              jq -e --arg name "$command" 'select(.id == "1") | .data.commands | map(.name) | index($name) != null' commands > /dev/null \
                || { echo "FAIL: no /$command command; an extension did not load"; cat commands; exit 1; }
            done
            touch "$out"
          '';
    };
}
