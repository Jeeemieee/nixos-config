# The pi coding agent, always run inside a bubblewrap sandbox; users opt in by importing homeManager.pi
# The sandbox sees the project (the git repository around the current folder, or the folder itself), ~/.pi, the Nix store and the network,
# and nothing else of the home folder, no session sockets (Docker, D-Bus, SSH agent, keyrings) and no other processes
let
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
    };
}
