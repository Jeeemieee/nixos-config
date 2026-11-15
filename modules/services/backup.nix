# Hourly restic backup of /home to the home server; hosts opt in by importing nixos.backup
# The server (rest-server in append-only mode) decides how long snapshots are kept: this machine can add snapshots, but cannot delete or change them
# The server's address and this machine's credentials come from restic_env and restic_password in secrets/<hostname>.yaml; this public file holds neither
{ inputs, ... }@topLevel:
let
  # A backup that is skipped because the server cannot be reached becomes a failure once the last successful one is older than this
  maxAgeHours = 24;
  # How long one run waits for the server; after sleep, Tailscale needs some seconds to reconnect
  waitSeconds = 60;

  unit = "restic-backups-home";
  stateDir = "/var/lib/${unit}";
  lastSuccess = "${stateDir}/last-success";
in
{
  flake.modules.nixos.backup =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      secretsFile = "${inputs.nixos-secrets}/secrets/${config.networking.hostName}.yaml";

      # Decides before every run: 0 = the server answers, run the backup; 1 = no route, skip quietly; 255 = fail
      # It sends no credentials: any HTTP answer from the server's address counts, also "401 Unauthorized"
      serverReachable = pkgs.writeShellScript "${unit}-server-reachable" ''
        case "''${RESTIC_REPOSITORY:-}" in
          rest:http://* | rest:https://*) url=''${RESTIC_REPOSITORY#rest:} ;;
          *)
            echo "RESTIC_REPOSITORY in restic_env must be a rest:http(s):// address; refusing to run" >&2
            exit 255
            ;;
        esac

        while [ "$SECONDS" -lt ${toString waitSeconds} ]; do
          if ${pkgs.curl}/bin/curl --silent --output /dev/null --max-time 5 "$url"; then
            exit 0
          fi
          sleep 3
        done

        # No route: quiet while the last successful backup is recent, a failure once it is not
        if [ -e ${lastSuccess} ] && [ $(($(date +%s) - $(stat -c %Y ${lastSuccess}))) -lt ${toString (maxAgeHours * 3600)} ]; then
          echo "The backup server cannot be reached; the last successful backup is less than ${toString maxAgeHours} hours old, skipping this run"
          exit 1
        fi
        echo "The backup server cannot be reached and there is no successful backup from the last ${toString maxAgeHours} hours" >&2
        exit 255
      '';
    in
    {
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # restic_env: the repository address and the rest-server login; restic_password: this machine's own key to the repository
      sops.secrets.restic_env = { sopsFile = secretsFile; };
      sops.secrets.restic_password = { sopsFile = secretsFile; };

      services.restic.backups.home = {
        # The whole of /home, so that a new folder is backed up without being listed; snapshots are stored under this machine's host name
        paths = [ "/home" ];
        environmentFile = config.sops.secrets.restic_env.path;
        passwordFile = config.sops.secrets.restic_password.path;

        # Only data that is rebuilt, downloaded again, or already thrown away; a pattern without a slash matches that name in every folder
        exclude = [
          # Simulation output that can be recreated; on machines with nixos.disk it is also a dataset of its own
          "/home/*/scratch"
          # Caches, rebuilt by the programs that own them
          "/home/*/.cache"
          # Files that were already deleted
          "/home/*/.local/share/Trash"
          # Rootless Docker's images, containers and volumes, pulled or built again
          "/home/*/.local/share/docker"
          # Development environments, rebuilt from flake.nix, pyproject.toml or package.json
          ".direnv"
          ".venv"
          "node_modules"
          # Python and Jupyter by-products
          "__pycache__"
          ".pytest_cache"
          ".ipynb_checkpoints"
        ];
        # The agent workers' folders are file systems of their own below ~/workers (nixos.disk, nixos.workers), which the rule below would skip:
        # every one that is mounted when the backup starts is named here. Their scratch areas are below ~/scratch and stay out
        # Only "nothing matched" is tolerated: a list that cannot be made fails the backup instead of leaving the workers out of it
        dynamicFilesFrom = ''
          #!${pkgs.runtimeShell}
          set -eu
          targets=$(${pkgs.util-linux}/bin/findmnt -rn -o TARGET)
          printf '%s\n' "$targets" | ${pkgs.gnugrep}/bin/grep -E '^/home/[^/]+/workers(/|$)' || [ "$?" = 1 ]
        '';
        extraBackupArgs = [
          # Stay on /home's own file system: never descend into other datasets, network drives or a mounted backup
          "--one-file-system"
          # Skip folders that mark themselves as a cache with a CACHEDIR.TAG file
          "--exclude-caches"
        ];

        # Hourly; a run missed while the machine was off or asleep is made up for when it is back on
        timerConfig = {
          OnCalendar = "hourly";
          Persistent = true;
          RandomizedDelaySec = "5m";
        };

        # Deliberately not set here: pruneOpts, checkOpts and initialize
        # Retention, pruning and integrity checks run on the server, the only place that may delete; the append-only server refuses them from this machine
        # The repository already exists; creating one here would hide a wrong address behind a new, empty repository
      };

      systemd.services.${unit} = {
        # sops-nix does not order its secrets before regular services; a failed decryption must fail this unit instead of running without credentials
        requires = [ "sops-install-secrets.service" ];
        # The workers' file systems are mounted by their own unit, on machines that have it; the backup lists them when it starts
        after = [
          "sops-install-secrets.service"
          "worker-datasets-mount.service"
        ];

        onFailure = [ "${unit}-failed.service" ];

        serviceConfig = {
          # Exit status 1 skips the run without marking the unit as failed; 255 fails it
          ExecCondition = serverReachable;
          StateDirectory = unit;
          # Only reached when restic succeeded; the reachability check reads this time stamp
          ExecStartPost = "${pkgs.coreutils}/bin/touch ${lastSuccess}";
        };
      };

      # A failed backup is shown on the desktop of whoever is logged in, in the same way as smartd's disk warnings
      systemd.services."${unit}-failed" = {
        description = "Report a failed backup on the desktop";
        serviceConfig = {
          Type = "oneshot";
          ExecStart = lib.concatStringsSep " " [
            "${pkgs.dbus}/bin/dbus-send --system / net.nuetzlich.SystemNotifications.Notify"
            ''"string:Backup failed"''
            ''"string:The backup of /home to the server did not complete. Details: journalctl -u ${unit}.service"''
          ];
        };
      };
      services.systembus-notify.enable = true;
    };

  perSystem =
    { pkgs, ... }:
    let
      inherit (pkgs) lib;
      modules = topLevel.config.flake.modules.nixos;

      # Test values only; the real ones are entered with `sops edit` and never appear in this repository
      login = "laptop";
      loginPassword = "test-login-password";
      repositoryPassword = "test-repository-password";

      # A throwaway age key and a secrets file encrypted for it, in the format of secrets/<hostname>.yaml; both are generated inside the build
      testSecrets =
        pkgs.runCommand "backup-test-secrets"
          {
            nativeBuildInputs = [
              pkgs.age
              pkgs.sops
            ];
          }
          ''
            export HOME=$TMPDIR
            mkdir "$out"
            age-keygen -o "$out/key.txt" 2>/dev/null
            cat > secrets.yaml <<EOF
            restic_env: |
                RESTIC_REPOSITORY='rest:http://server:8000/${login}/'
                RESTIC_REST_USERNAME='${login}'
                RESTIC_REST_PASSWORD='${loginPassword}'
            restic_password: ${repositoryPassword}
            EOF
            sops encrypt --age "$(age-keygen -y "$out/key.txt")" secrets.yaml > "$out/secrets.yaml"
          '';

      # The login file of the test server, bcrypt as on the real server
      htpasswd = pkgs.runCommand "backup-test-htpasswd" { nativeBuildInputs = [ pkgs.apacheHttpd ]; } ''
        htpasswd -nbB ${login} ${loginPassword} > "$out"
      '';

      # T1's oracle: the SHA-256 of knownContent, computed with sha256sum outside this test
      knownContent = "restore-oracle 2026-11-12: byte-identical or it fails";
      knownSha256 = "ed7f60e3218e0365ea5a5f3a0cd2e20cc96c93e6b2c5eb932e09015e75555df0";
    in
    {
      # The backup against a throwaway rest-server of the same kind as the real one (append-only, one private repository per login); no network, no real secrets
      checks.backup =
        pkgs.testers.runNixOSTest {
          name = "backup";

          nodes.server = {
            services.restic.server = {
              enable = true;
              appendOnly = true;
              privateRepos = true;
              listenAddress = "8000";
              htpasswd-file = "${htpasswd}";
            };
            networking.firewall.allowedTCPPorts = [ 8000 ];
          };

          nodes.laptop =
            { lib, ... }:
            {
              imports = [ modules.backup ];

              # The test's own secrets instead of nixos-secrets; the machine key is installed by the test script, as an enrolment would
              sops.validateSopsFiles = false;
              sops.secrets.restic_env.sopsFile = lib.mkForce "${testSecrets}/secrets.yaml";
              sops.secrets.restic_password.sopsFile = lib.mkForce "${testSecrets}/secrets.yaml";

              users.users.tester = {
                isNormalUser = true;
                uid = 1000;
              };

              # Stands in for the unit that mounts the workers' folders (nixos.workers), here failing: the backup of /home must still run
              systemd.services.worker-datasets-mount = {
                wantedBy = [ "multi-user.target" ];
                serviceConfig = {
                  Type = "oneshot";
                  ExecStart = "${pkgs.coreutils}/bin/false";
                };
              };
            };

          testScript = ''
            import json

            UNIT = "${unit}.service"
            HOME = "/home/tester"

            def snapshots_on_server():
                # Counted in the server's own storage, not through the laptop's restic; the folder does not exist before the repository does
                snapshots = "/var/lib/restic/${login}/snapshots"
                return int(server.succeed(f"if [ -d {snapshots} ]; then ls {snapshots} | wc -l; else echo 0; fi").strip())

            def show(prop):
                return laptop.succeed(f"systemctl show -p {prop} --value {UNIT}").strip()

            def notifications():
                return int(laptop.succeed("journalctl -u signal-monitor.service --no-pager | grep -c 'string \"Backup failed\"' || true").strip())

            def expect_notification(count):
                laptop.wait_until_succeeds(f"test \"$(journalctl -u signal-monitor.service --no-pager | grep -c 'string \"Backup failed\"')\" = {count}", timeout=60)

            start_all()
            server.wait_for_unit("restic-rest-server.socket")
            laptop.wait_for_unit("multi-user.target")

            # The schedule: hourly, made up for after a missed run; the timer is then stopped so that only this script starts backups
            laptop.succeed("systemctl is-active restic-backups-home.timer")
            assert "*-*-* *:00:00" in laptop.succeed("systemctl show -p TimersCalendar --value restic-backups-home.timer")
            assert laptop.succeed("systemctl show -p Persistent --value restic-backups-home.timer").strip() == "yes"
            laptop.succeed("systemctl stop restic-backups-home.timer")

            # Everything the failure unit sends to the desktop is recorded from the system bus
            laptop.succeed("systemd-run --unit=signal-monitor ${pkgs.dbus}/bin/dbus-monitor --system \"interface='net.nuetzlich.SystemNotifications'\"")
            laptop.sleep(5)

            with subtest("T4b: secrets that cannot be decrypted fail the backup and are reported"):
                # A new machine has its own key, for which the secrets are not encrypted
                laptop.succeed("systemctl is-failed sops-install-secrets.service")
                laptop.fail(f"systemctl start {UNIT}")
                expect_notification(1)
                assert snapshots_on_server() == 0

            # Enrol the machine: install the key the test secrets are encrypted for
            laptop.succeed("install -m 600 ${testSecrets}/key.txt /var/lib/sops-nix/key.txt")
            laptop.succeed("systemctl restart sops-install-secrets.service")
            for secret in ["restic_env", "restic_password"]:
                laptop.succeed(f"test \"$(stat -Lc '%a %U:%G' /run/secrets/{secret})\" = '400 root:root'")
            # The repository exists before the first backup, as on the real server
            laptop.succeed("restic-home init")

            # One file in every excluded place, and one next to each that must be kept
            excluded = [
                f"{HOME}/scratch/output.dat",
                f"{HOME}/.cache/cached",
                f"{HOME}/.local/share/Trash/files/deleted",
                f"{HOME}/.local/share/docker/overlay2/layer",
                f"{HOME}/project/.direnv/env",
                f"{HOME}/project/.venv/pyvenv.cfg",
                f"{HOME}/project/node_modules/package/index.js",
                f"{HOME}/project/__pycache__/module.pyc",
                f"{HOME}/project/.pytest_cache/lastfailed",
                f"{HOME}/project/.ipynb_checkpoints/notebook.ipynb",
                f"{HOME}/project/tagged-cache/cached",
                f"{HOME}/mounted/elsewhere",
            ]
            kept = [
                f"{HOME}/documents/known.txt",
                f"{HOME}/keep-home.txt",
                f"{HOME}/.local/share/keep-share.txt",
                f"{HOME}/project/keep-project.txt",
                f"{HOME}/project/.pi/work/keep-agent-work.txt",
                f"{HOME}/workers/project/old/keep-by-hand.txt",
                f"{HOME}/workers/project/branch/name/repo/keep-worker.txt",
            ]
            # Another file system inside /home, like the scratch dataset or a mounted backup
            laptop.succeed(f"su tester -c 'mkdir {HOME}/mounted' && mount -t tmpfs tmpfs {HOME}/mounted && chown tester {HOME}/mounted")
            # ~/workers is a file system of its own, as on the laptop; a folder made in it by hand belongs in the backup
            laptop.succeed(f"mkdir {HOME}/workers && mount -t tmpfs tmpfs {HOME}/workers && chown tester {HOME}/workers")
            # A worker's folder: one more file system of its own below ~/workers, which belongs in the backup too
            laptop.succeed(f"su tester -c 'mkdir -p {HOME}/workers/project/branch/name' && mount -t tmpfs tmpfs {HOME}/workers/project/branch/name && chown tester {HOME}/workers/project/branch/name")
            for path in excluded + kept:
                laptop.succeed(f"su tester -c 'mkdir -p \"$(dirname {path})\" && echo data > {path}'")
            laptop.succeed(f"su tester -c \"printf 'Signature: 8a477f597d28d172789f06886806bc55\\n' > {HOME}/project/tagged-cache/CACHEDIR.TAG\"")
            laptop.succeed(f"su tester -c \"printf '${knownContent}\\n' > {HOME}/documents/known.txt\"")

            with subtest("T1: a backup succeeds and a known file is restored byte-identical"):
                # Also while the unit that mounts the workers' folders has failed
                laptop.succeed("systemctl is-failed worker-datasets-mount.service")
                laptop.succeed(f"systemctl start {UNIT}")
                assert snapshots_on_server() == 1
                laptop.succeed("mkdir /root/restore && test -z \"$(ls -A /root/restore)\"")
                laptop.succeed(f"restic-home restore latest --target /root/restore --include {HOME}/documents/known.txt")
                laptop.succeed(f"cmp {HOME}/documents/known.txt /root/restore{HOME}/documents/known.txt")
                assert laptop.succeed(f"sha256sum < /root/restore{HOME}/documents/known.txt").split()[0] == "${knownSha256}"

            with subtest("T2: excluded folders are absent from the snapshot, their neighbours are present"):
                listed = set(laptop.succeed("restic-home ls latest").splitlines())
                for path in kept:
                    assert path in listed, f"missing from the snapshot: {path}"
                for path in excluded:
                    assert path not in listed, f"in the snapshot but excluded: {path}"

            with subtest("T5: the laptop's credentials cannot delete a snapshot"):
                snapshot = json.loads(laptop.succeed("restic-home snapshots --json"))[0]["id"]
                # restic's exit status is not checked: 0.18.1 reports the refusal and still exits with 0, 0.19.1 exits with an error
                _, output = laptop.execute(f"restic-home forget {snapshot} 2>&1")
                print(output)
                assert "403" in output, "forget was not refused with 403 Forbidden"
                # The same request without restic in between: the server itself answers 403
                delete = f"curl --silent --output /dev/null --write-out '%{{http_code}}' --request DELETE --user ${login}:${loginPassword} http://server:8000/${login}/snapshots/{snapshot}"
                assert laptop.succeed(delete).strip() == "403"
                server.succeed(f"test -s /var/lib/restic/${login}/snapshots/{snapshot}")
                assert snapshots_on_server() == 1

            with subtest("T3: no route skips the run quietly, the next run with a route succeeds, and a stale backup without a route fails"):
                server.block()
                laptop.execute(f"systemctl start {UNIT}")
                assert show("Result") == "exec-condition", show("Result")
                assert show("ActiveState") == "inactive", show("ActiveState")
                laptop.fail(f"systemctl is-failed {UNIT}")
                assert snapshots_on_server() == 1
                assert notifications() == 1

                server.unblock()
                laptop.succeed(f"systemctl start {UNIT}")
                assert snapshots_on_server() == 2

                laptop.succeed("touch -d '25 hours ago' ${lastSuccess}")
                server.block()
                laptop.fail(f"systemctl start {UNIT}")
                laptop.succeed(f"systemctl is-failed {UNIT}")
                expect_notification(2)
                assert snapshots_on_server() == 2
                server.unblock()

            with subtest("T4a: a wrong repository password fails the backup and is reported"):
                laptop.succeed("printf 'not-the-password' > /run/secrets/restic_password")
                laptop.fail(f"systemctl start {UNIT}")
                laptop.succeed(f"systemctl is-failed {UNIT}")
                assert show("Result") == "exit-code", show("Result")
                expect_notification(3)
                assert snapshots_on_server() == 2

            with subtest("T8: a repository that is not a rest-server address is refused"):
                laptop.succeed("printf \"RESTIC_REPOSITORY='sftp:backup@server:/srv/restic'\\n\" > /run/secrets/restic_env")
                laptop.fail(f"systemctl start {UNIT}")
                laptop.succeed(f"journalctl -u {UNIT} --no-pager | grep -q 'must be a rest:http(s):// address; refusing to run'")
                expect_notification(4)
                assert snapshots_on_server() == 2

            # With the secrets decrypted again, the backup works as before
            laptop.succeed("systemctl restart sops-install-secrets.service")
            laptop.succeed(f"systemctl start {UNIT}")
            laptop.fail(f"systemctl is-failed {UNIT}")
            assert snapshots_on_server() == 3
            assert notifications() == 4
          '';
        };
    };
}
