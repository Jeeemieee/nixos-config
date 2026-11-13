# The pi coding agent, always run inside a bubblewrap sandbox; users opt in by importing homeManager.pi
# The sandbox sees the project (the git repository around the current folder, or the folder itself), ~/.pi, the Nix store and the network,
# and nothing else of the home folder, no session sockets (Docker, D-Bus, SSH agent, keyrings) and no other processes
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
        (npm "@juicesharp/rpiv-todo" "2.15.0" "sha512-8WfYssdgQgSWzFNsRzdw5Z6ZJIjO2ecM/YqEzYpR/ore+Hh5aNmafGVy94uFbIofAv2wGGitx5e3J/ucRrViXQ==")
        (npm "@juicesharp/rpiv-ask-user-question" "2.15.0" "sha512-Gm6de5IZF52BaSeh9dnDqJBn821Z5XfJkCmhkCmqTzvNv3SCpSv1mA4Gj5VBcfrSe+xTtWSVQzJwIqJFQHH3Lg==")
        # Not an extension: the dependency of the two rpiv extensions
        (npm "@juicesharp/rpiv-config" "2.15.0" "sha512-S2BAGX4dJjQ2AyNYOEjC6ha04p9f6CdEfmtxpdxzSKrfDMwqIvOjjO9HiHc1IPY7jDY1q2Q8cGCtpIZWV6Y8NQ==")
        (npm "@geminixiang/pi-simplify" "0.2.0" "sha512-pASkAwxqwU7vB8phjir1h50jSaSwaziro/R3FbKC+GMtNdFNDVybTe1VQ0gcKQ5l6fVoxm5NhyZ30XUdKqM68g==")
        (npm "@gotgenes/pi-anthropic-auth" "3.4.4" "sha512-oWCkPFSa7AkvSju3OrlYu0GTo8Jdqz2OvszJtHj0hzXLw8tErtmPPMYPqK2it3zaXu+Wl2oH8nfpeIUVsqW2Vw==")
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
    pkgs.runCommand "pi-extensions" { } (
      pkgs.lib.concatMapStrings (package: ''
        mkdir -p "$out/node_modules/${package.name}"
        ${package.unpack} "$out/node_modules/${package.name}"
      '') packages
    );

  # ~/.pi/agent/settings.json; pi cannot change it, so /settings and `pi install` do not persist
  settingsFor = extensions: {
    theme = "dark";
    defaultProvider = "openai-codex";
    defaultModel = "gpt-5.6-sol";
    defaultThinkingLevel = "high";
    packages = map (name: "${extensions}/node_modules/${name}") extensionNames;
  };

  # Build a sandboxed launcher; the checks reuse it with a probe instead of pi
  mkSandbox =
    pkgs:
    {
      name,
      command,
      environment ? { },
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
        while [ "$#" -gt 0 ]; do
          case "$1" in
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

        # The project is the git repository around the current folder, or the folder itself
        workdir=$(pwd -P)
        project=$(git -C "$workdir" rev-parse --show-toplevel 2>/dev/null || echo "$workdir")
        checkPath "$project"

        # Git hooks and the repository config run commands outside the sandbox later (hooks, core.fsmonitor), so the sandbox may not change them
        protect=()
        for path in "$project/.git/hooks" "$project/.git/config"; do
          if [ -e "$path" ]; then protect+=(--ro-bind "$path" "$path"); fi
        done

        mkdir -p "$HOME/.pi"

        exec bwrap \
          --unshare-all --share-net --die-with-parent \
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
          --bind "$HOME/.pi" "$HOME/.pi" \
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
          ${pkgs.lib.concatStringsSep " " (pkgs.lib.mapAttrsToList (key: value: "--setenv ${key} ${pkgs.lib.escapeShellArg value}") environment)} \
          -- ${command} "$@"
      '';
    };
in
{
  flake.modules.homeManager.pi =
    { pkgs, ... }:
    let
      # Nix owns pi's version; `pi update` explains that instead of installing over the store
      noSelfUpdate = pkgs.writeShellScript "pi-no-self-update" ''
        echo "pi is managed by Nix: update it with 'nix flake update nixpkgs-unstable' in ~/repos/nixos-config and rebuild" >&2
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
        })
      ];

      # Links into the Nix store: read-only for everyone, also inside the sandbox, where ~/.pi itself is writable
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
        if [ -e "$HOME/.config/restic/password" ]; then report restic visible; else report restic hidden; fi
        if [ -e "$HOME/other-project/file" ]; then report other visible; else report other hidden; fi
        if echo ok > "$PWD/written-inside"; then report project writable; else report project readonly; fi
        echo leak > "$HOME/leaked" 2>/dev/null || true
        if echo hook >> "$PROJECT/.git/hooks/post-checkout" 2>/dev/null; then report hooks writable; else report hooks readonly; fi
        if [ -e "$HOME/.pi/marker" ]; then report pi-config visible; else report pi-config hidden; fi
        if [ -e "$HOME/data/allowed" ]; then report allowed visible; else report allowed hidden; fi
        if [ -n "''${SSH_AUTH_SOCK:-}" ]; then report ssh-agent set; else report ssh-agent unset; fi
        report pid1 "$(cat /proc/1/comm)"
        report version-check "''${PI_SKIP_VERSION_CHECK:-unset}"
        if [ "$(cat "$HOME/.pi/agent/AGENTS.md" 2>/dev/null)" != rules ]; then report instructions unreadable
        elif echo more >> "$HOME/.pi/agent/AGENTS.md" 2>/dev/null; then report instructions writable
        else report instructions readonly; fi
        case "$(command -v xdg-open)" in
          *-pi-sandbox-no-browser/bin/xdg-open) if xdg-open https://example.org; then report opener opened; else report opener quiet-failure; fi ;;
          *) report opener system ;;
        esac
      '';
      sandboxedProbe = mkSandbox pkgs {
        name = "pi";
        command = "${probe}";
        environment.PI_SKIP_VERSION_CHECK = "1";
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
            touch "$HOME/.ssh/id_test" "$HOME/.config/restic/password" "$HOME/.pi/marker" "$HOME/other-project/file" "$HOME/data/allowed"
            # Declared files are links into the store, as Home Manager creates them
            mkdir -p "$HOME/.pi/agent"
            ln -s ${pkgs.writeText "pi-sandbox-rules" "rules"} "$HOME/.pi/agent/AGENTS.md"
            git -C "$HOME/project" init -q
            touch "$HOME/project/.git/hooks/post-checkout"
            mkdir -p "$HOME/project/sub"

            # Normal use from a subfolder of the project, with one extra folder allowed read-only
            (cd "$HOME/project/sub" && PROJECT=$HOME/project ${sandboxedProbe}/bin/pi --allow-ro "$HOME/data") > actual
            cat > expected <<EOF
            ssh=hidden
            restic=hidden
            other=hidden
            project=writable
            hooks=readonly
            pi-config=visible
            allowed=visible
            ssh-agent=unset
            pid1=bwrap
            version-check=1
            instructions=readonly
            opener=quiet-failure
            EOF
            sed -i 's/^ *//' expected
            diff expected actual
            [ -e "$HOME/project/sub/written-inside" ] || { echo "FAIL: project write did not reach the host"; exit 1; }
            [ ! -e "$HOME/leaked" ] || { echo "FAIL: a write to the sandbox home reached the real home"; exit 1; }
            [ ! -s "$HOME/project/.git/hooks/post-checkout" ] || { echo "FAIL: the sandbox changed a git hook"; exit 1; }

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
            touch "$out"
          '';
    };
}
