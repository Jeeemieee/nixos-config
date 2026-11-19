# Several coding agents ("workers") on one machine
#
# What it is    The layout (a folder and a scratch area per worker, each with its own limit, and the sizes of a sandbox's folders
#               in memory), the queue (a broker per sandbox that runs queued jobs in a second sandbox with the same view), the
#               resource groups of agents and jobs, and the commands workers, queue and intent; see docs/WORKERS.md
# Who uses it   A NixOS host by importing nixos.workers; the pi launcher (modules/dev/pi.nix) applies what is set here
# A host adds   hostSpec.workers: the user, and every limit and number of docs/WORKERS.md, "Every number, in one place"
# Protected     Yes: it defines limits, the root helper with its sudo rule, system units and checks (docs/UPKEEP.md)
{ inputs, config, ... }:
let
  topLevel = config;
  # The roles a worker can have; each has a text of instructions of its own
  roles = [
    "implementer"
    "reviewer"
    "deep-reviewer"
    "manager"
  ];
in
{
  flake.modules.nixos.workers =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      cfg = config.hostSpec.workers;
      # Not read from the account: the two parents are file systems, and the list of accounts depends on the file systems
      workersPath = "/home/${cfg.user}/workers";
      scratchPath = "/home/${cfg.user}/scratch/workers";
      # With nixos.disk both parents are datasets, declared there; without it the workers get plain folders
      datasetAt =
        path:
        if (config.fileSystems.${path}.fsType or null) == "zfs" then
          config.fileSystems.${path}.device
        else
          null;
      zfs = datasetAt workersPath != null && datasetAt scratchPath != null;

      # The only part that runs as root: ZFS on Linux lets nobody else mount a dataset
      helper = pkgs.writeShellApplication {
        name = "worker-datasets";
        runtimeInputs = [
          config.boot.zfs.package
          pkgs.coreutils
          pkgs.util-linux
        ];
        text = ''
          WORKERS_DATASET=${lib.escapeShellArg (datasetAt workersPath)}
          WORKERS_PATH=${lib.escapeShellArg workersPath}
          SCRATCH_DATASET=${lib.escapeShellArg (datasetAt scratchPath)}
          SCRATCH_PATH=${lib.escapeShellArg scratchPath}
          OWNER=${lib.escapeShellArg cfg.user}
          FOLDER_QUOTA=${lib.escapeShellArg cfg.folderQuota}
          AREA_QUOTA=${lib.escapeShellArg cfg.areaQuota}
          INSTRUCTIONS_QUOTA=${lib.escapeShellArg cfg.instructionsQuota}
          HOLD_DAYS=${toString cfg.holdDays}
        ''
        + builtins.readFile ../../workers/worker-datasets.sh;
      };

      systemd = config.systemd.package;
      python = "${pkgs.python3}/bin/python3 -I";
      # The largest text of an agent's or a manager's that a tool reads as a whole: a task file, an intent form
      maxTextBytes = 256 * 1024;
      # The Python sources are checked when the system is built
      checked =
        file:
        pkgs.runCommand (baseNameOf file) { nativeBuildInputs = [ pkgs.python3Packages.pyflakes ]; } ''
          pyflakes ${file}
          cp ${file} "$out"
        '';

      # The first program inside every job's sandbox
      jobWrapper = pkgs.writeShellApplication {
        name = "queue-job";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.git
        ];
        text = builtins.readFile ../../workers/queue-job.sh;
      };

      # Starts a job's sandbox, inside the job's resource group and outside the sandbox: job-measure <file> <sandbox command...>
      # When the sandbox has ended, the group still exists, because this program is in it: it writes down the job's highest
      # memory and how many of its processes the kernel stopped for memory, for the run's record
      jobMeasure = pkgs.writeShellScript "job-measure" ''
        file=$1
        shift
        # (this shell's own word on how the sandbox ended goes nowhere; the sandbox keeps the job's error stream)
        exec 3>&2 2> /dev/null
        "$@" 2>&3 3>&-
        status=$?
        group=/sys/fs/cgroup$(${pkgs.gnused}/bin/sed -n 's/^0:://p' /proc/self/cgroup)
        {
          ${pkgs.coreutils}/bin/cat "$group/memory.peak"
          ${pkgs.gawk}/bin/awk '$1 == "oom_kill" { print $2 }' "$group/memory.events"
        } > "$file" 2> /dev/null
        exit "$status"
      '';

      # The first program of an acceptance run, after queue-job: the worker's commit and the project's tests, in the job's own /tmp
      acceptanceJob = pkgs.writeShellApplication {
        name = "acceptance-job";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.git
          pkgs.gnutar
        ];
        text = builtins.readFile ../../workers/acceptance-job.sh;
      };

      # The one parser and writer for persistent worker starts
      startSpecProgram = checked ../../workers/start-spec.py;
      startSpecCommand = [
        "${pkgs.python3}/bin/python3"
        "-I"
        "${startSpecProgram}"
      ];
      # The bundle client also supplies the broker's fixed creator inside the checked repository sandbox
      workerBundleProgram = checked ../../workers/worker-bundle.py;
      workerBundleCommand = [
        "${pkgs.python3}/bin/python3"
        "-I"
        "${workerBundleProgram}"
      ];
      # The check of an implementer's intent form: the worker runs it inside its sandbox, `workers approve` outside
      intentCheck = checked ../../workers/intent-check.py;
      # What `workers approve` starts, by fixed paths
      approveSettings = {
        readChecked = [
          "${pkgs.python3}/bin/python3"
          "-I"
          "${checked ../../workers/read-checked.py}"
        ];
        intentCheck = [
          "${pkgs.python3}/bin/python3"
          "-I"
          "${intentCheck}"
        ];
        git = "${pkgs.git}/bin/git";
        systemctl = "${systemd}/bin/systemctl";
        # On a terminal the form is shown in a viewer that waits; q closes it
        viewer = [ "${pkgs.less}/bin/less" ];
        # Empty on a machine with plain folders
        helper = lib.optionals zfs [
          "/run/wrappers/bin/sudo"
          "-n"
          "${helper}/bin/worker-datasets"
        ];
        # A form is shown to the user in full, so it has the size limit of a task file
        maxFormBytes = maxTextBytes;
      };
      approveConfig = pkgs.writeText "worker-approve.json" (builtins.toJSON approveSettings);
      approveProgram = checked ../../workers/approve.py;
      # The one program that reads and judges approvals: for the user, for the launcher (--state) and for the broker (--acceptance)
      approveCommand = [
        "${pkgs.python3}/bin/python3"
        "-I"
        "${approveProgram}"
        "--config"
        "${approveConfig}"
      ];
      # `workers status`: what it reads, by fixed paths; it judges approvals with the program above
      statusConfig = pkgs.writeText "worker-status.json" (
        builtins.toJSON {
          approve = "${approveProgram}";
          approveConfig = approveSettings;
          startSpec = "${startSpecProgram}";
          git = "${pkgs.git}/bin/git";
          findmnt = "${pkgs.util-linux}/bin/findmnt";
          inherit (approveSettings) helper;
          locks = "/run/worker-queue";
          inherit (cfg) timingCpus;
        }
      );
      statusCommand = "${python} ${checked ../../workers/status.py} --config ${statusConfig}";
      # The live overview (workers-dashboard/): it only displays, and asks the status's program above for its document
      watch = import ../../workers-dashboard/package.nix pkgs {
        statusCommand = lib.splitString " " statusCommand ++ [ "--json" ];
      };

      # The broker starts every program by one of these paths, never by a name a request could influence
      brokerConfig = pkgs.writeText "worker-broker.json" (
        builtins.toJSON {
          locks = "/run/worker-queue";
          inherit (cfg)
            timingCpus
            workCpus
            maxRequests
            maxSlots
            jobProcessors
            maxRunSeconds
            ;
          allCpus = lib.concatStringsSep "," (
            builtins.filter (set: set != "") [
              cfg.timingCpus
              cfg.workCpus
            ]
          );
          maxRequestBytes = 1048576;
          # One piece of a manager's read of another worker; larger regular files are read with another offset
          maxReadBytes = maxTextBytes;
          # A bundle is streamed through the broker, never retained there as a whole
          maxBundleBytes = cfg.bundleMiB * 1024 * 1024;
          # A request arrives at once or not at all, so the whole of it has this long; connections without one are few
          requestSeconds = 10;
          maxConnections = 16;
          choom = "${pkgs.util-linux}/bin/choom";
          git = "${pkgs.git}/bin/git";
          openChecked = [
            "${pkgs.python3}/bin/python3"
            "-I"
            "${checked ../../workers/open-checked.py}"
          ];
          # A job is stopped before an agent when memory runs out
          jobOomScoreAdjust = 500;
          bwrap = "${pkgs.bubblewrap}/bin/bwrap";
          systemdRun = "${systemd}/bin/systemd-run";
          systemctl = "${systemd}/bin/systemctl";
          jobWrapper = "${jobWrapper}/bin/queue-job";
          # An acceptance run: which tests and which command, and the first program of its job
          approve = approveCommand;
          acceptanceJob = "${acceptanceJob}/bin/acceptance-job";
          jobMeasure = "${jobMeasure}";
          workerBundleCreate = workerBundleCommand ++ [ "--create" ];
          workerBundleHistory = workerBundleCommand ++ [ "--project-history" ];
        }
      );

      # Runs inside the agent's new scope, still outside the sandbox: starts this sandbox's broker, bound to the scope, then the sandbox
      # The launcher exports what the broker needs; none of it reaches the sandbox
      # When the sandbox has ended, the broker ends with it, and after it the sandbox's runtime state is removed: its folder
      # with the view and the socket, and the copies of the task and of the project's rules beside it
      start = pkgs.writeShellScript "worker-start" ''
        # The scope is active and its mount-view record exists now, so removal can use those facts instead of the launcher's lifecycle lock
        exec 8>&-
        ${systemd}/bin/systemd-run --user --quiet --collect --expand-environment=no --unit="broker-$WORKER_UNIT" --slice=workers-brokers.slice \
          -p BindsTo="$WORKER_UNIT.scope" -p After="$WORKER_UNIT.scope" -p MemoryMax=${cfg.brokerMemory} -p MemorySwapMax=0 \
          -p ExecStopPost="${pkgs.coreutils}/bin/rm -rf $WORKER_STATE $WORKER_STATE.task $WORKER_STATE.rules" \
          -- ${python} ${checked ../../workers/broker.py} --config ${brokerConfig} --dir "$WORKER_STATE" --unit "$WORKER_UNIT" \
          --records "$WORKER_RECORDS" --records-limit "$WORKER_RECORDS_LIMIT" --scratch "$WORKER_AREA" --repo "$WORKER_REPO" \
          --workers-root "$WORKER_FOLDERS" --roles-root "$WORKER_ROLES" --identity "$WORKER_IDENTITY" \
          || { echo "the broker of this sandbox could not be started, so the sandbox does not start" >&2; exit 2; }
        for _ in $(${pkgs.coreutils}/bin/seq 50); do
          if [ -S "$WORKER_STATE/socket/queue.sock" ]; then break; fi
          ${pkgs.coreutils}/bin/sleep 0.1
        done
        [ -S "$WORKER_STATE/socket/queue.sock" ] || { echo "the broker of this sandbox did not come up, so the sandbox does not start" >&2; exit 2; }
        unset WORKER_UNIT WORKER_STATE WORKER_RECORDS WORKER_RECORDS_LIMIT WORKER_AREA WORKER_REPO WORKER_FOLDERS WORKER_ROLES WORKER_IDENTITY
        # The launcher's lock on this worker's name is given up after the running scope exists
        exec "$@" 9>&-
      '';

      # Makes a worker's own copy of the project, inside its sandbox
      prepareCopy = pkgs.writeShellApplication {
        name = "prepare-copy";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.git
        ];
        text = ''
          INTENT_TEMPLATE=${../../workers/intent-template.md}
        ''
        + builtins.readFile ../../workers/prepare-copy.sh;
      };

      # The user's own command: what exists of the workers, removing and restoring one, and taking the manager's prepared work
      workersTool = pkgs.writeShellApplication {
        name = "workers";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.git
          pkgs.bubblewrap
          pkgs.util-linux
          pkgs.gnugrep
          systemd
        ];
        text = ''
          HELPER=${
            lib.escapeShellArg (if zfs then "/run/wrappers/bin/sudo -n ${helper}/bin/worker-datasets" else "")
          }
          HOLD_DAYS=${toString cfg.holdDays}
          QUESTION_SECONDS=${toString cfg.questionSeconds}
          QUESTION_MEMORY=${lib.escapeShellArg cfg.agentMemory}
          FOUND_LARGE_BYTES=${toString (cfg.foundLargeMiB * 1024 * 1024)}
          APPROVE=${lib.escapeShellArg (lib.concatStringsSep " " approveCommand)}
          STATUS=${lib.escapeShellArg statusCommand}
          START_SPEC=${lib.escapeShellArg (lib.concatStringsSep " " startSpecCommand)}
          PI=${lib.escapeShellArg "/etc/profiles/per-user/${cfg.user}/bin/pi"}
          WATCH=${watch}/bin/workers-watch
        ''
        + builtins.readFile ../../workers/workers.sh;
      };

      queue = pkgs.writeShellScriptBin "queue" ''
        exec ${python} ${checked ../../workers/queue.py} "$@"
      '';

      # A manager's read-only route to every worker's reports and records, including workers made after this sandbox started
      workerRead = pkgs.writeShellScriptBin "worker-read" ''
        exec ${python} ${checked ../../workers/worker-read.py} "$@"
      '';

      # A manager's bounded route to one worker's committed branch
      workerBundle = pkgs.writeShellScriptBin "worker-bundle" ''
        exec ${lib.concatStringsSep " " workerBundleCommand} "$@"
      '';

      # The worker's own command for the check of its form
      intent = pkgs.writeShellScriptBin "intent" ''
        if [ "''${1:-}" != check ] || [ "$#" -gt 2 ]; then
          echo "usage: intent check [<file>]   (without a file: this worker's reports/intent.md)" >&2
          exit 2
        fi
        exec ${python} ${intentCheck} ${toString maxTextBytes} "''${2:-$HOME/workers/''${WORKER_PROJECT:-}/''${WORKER_BRANCH:-}/''${WORKER_NAME:-}/reports/intent.md}"
      '';

      # The slots of the queue: empty files of root's, in memory. A broker holds a slot by a file lock, which needs no write access and
      # which the kernel drops when the broker ends; a reboot starts with new files
      lockFiles =
        map (index: "slot${toString index}") (lib.range 1 cfg.slots)
        ++ map (index: "parallel${toString index}") (lib.range 1 cfg.parallelTokens)
        ++ [
          "timing"
          "turnstile"
          "heavy"
        ];
    in
    {
      options.hostSpec.workers = {
        user = lib.mkOption {
          type = lib.types.str;
          description = "The user whose pi sandboxes are the workers; their folders are in this user's ~/workers and ~/scratch/workers.";
        };
        folderQuota = lib.mkOption {
          type = lib.types.str;
          default = "10G";
          description = "Upper limit of one worker's folder: its copy of the project, its reports and its pi sessions (ZFS only).";
        };
        areaQuota = lib.mkOption {
          type = lib.types.str;
          default = "50G";
          description = "Upper limit of one worker's scratch area (ZFS only).";
        };
        instructionsQuota = lib.mkOption {
          type = lib.types.str;
          default = "1G";
          description = "Upper limit of a project's folder of task files, which its manager writes (ZFS only).";
        };
        tmpfsMiB = lib.mkOption {
          type = lib.types.attrsOf lib.types.ints.positive;
          default = {
            tmp = 1024;
            home = 1024;
            run = 64;
            shm = 1024;
          };
          description = "Sizes in MiB of a sandbox's folders in memory: /tmp, the home folder, /run and /dev/shm. A full one returns an error to the writer.";
        };
        slots = lib.mkOption {
          type = lib.types.ints.positive;
          default = 5;
          description = "How many jobs of `queue run` run at once, on the whole machine.";
        };
        maxSlots = lib.mkOption {
          type = lib.types.ints.positive;
          default = 2;
          description = "How many queue slots one sandbox may hold at once. More requests wait without holding a slot.";
        };
        jobProcessors = lib.mkOption {
          type = lib.types.ints.positive;
          default = 2;
          description = "Processor time of one run job without --parallel, or one acceptance job, in CPUs. Timing and exclusive jobs keep their own rules.";
        };
        parallelTokens = lib.mkOption {
          type = lib.types.ints.positive;
          default = 1;
          description = "How many of them may run concurrent processes themselves (`queue run --parallel`).";
        };
        maxRequests = lib.mkOption {
          type = lib.types.ints.positive;
          default = 8;
          description = "How many requests one sandbox may have waiting or running in the queue; more are refused.";
        };
        maxRunSeconds = lib.mkOption {
          type = lib.types.submodule {
            options =
              lib.genAttrs
                [
                  "run"
                  "timing"
                  "exclusive"
                ]
                (
                  mode:
                  lib.mkOption {
                    type = lib.types.ints.unsigned;
                    default = 0;
                    description = "Seconds after which a `queue ${mode}` job is stopped; 0 for no limit.";
                  }
                );
          };
          default = { };
          description = "The longest a queued job may run, per mode. A job beyond it is stopped, and its record says so. Off unless set.";
        };
        timingCpus = lib.mkOption {
          type = lib.types.str;
          default = "";
          example = "0-3";
          description = "The CPUs of the timing jobs, as whole physical cores. While a timing job runs, everything else of the user is kept off them. Empty: timing jobs run one at a time, on any core.";
        };
        workCpus = lib.mkOption {
          type = lib.types.str;
          default = "";
          example = "4-27";
          description = "Every other CPU: where everything else of the user runs while a timing job does, and where Nix builds always run.";
        };
        totalMemory = lib.mkOption {
          type = lib.types.str;
          example = "18G";
          description = "Memory limit of all sandboxes and their jobs together; they have no swap.";
        };
        agentsMemory = lib.mkOption {
          type = lib.types.str;
          example = "8G";
          description = "Memory limit of all agents together, without their jobs, so that jobs keep a share of the total.";
        };
        agentMemory = lib.mkOption {
          type = lib.types.str;
          example = "6G";
          description = "Memory limit of one agent's sandbox, its folders in memory included. A queued job is not in it.";
        };
        agentsCpuQuota = lib.mkOption {
          type = lib.types.str;
          default = "400%";
          description = "Processor time of all agents together, without their jobs: 100% is one CPU.";
        };
        processorWeight = lib.mkOption {
          type = lib.types.ints.between 1 10000;
          default = 100;
          description = "Processor weight of the workers' whole resource group against the user's other groups; systemd's default is 100.";
        };
        brokerMemory = lib.mkOption {
          type = lib.types.str;
          default = "64M";
          description = "Memory limit of one sandbox's broker.";
        };
        nixDaemonMemory = lib.mkOption {
          type = lib.types.str;
          default = "12G";
          description = "Memory limit of the Nix daemon's builds, which run outside every sandbox.";
        };
        questionSeconds = lib.mkOption {
          type = lib.types.ints.positive;
          default = 60;
          description = "How long `workers remove` waits for git's answer on uncommitted changes in a worker's copy, which the worker's own settings can delay.";
        };
        foundLargeMiB = lib.mkOption {
          type = lib.types.ints.positive;
          default = 10;
          description = "An untracked file larger than this is left out by `workers found`, and named, unless it is asked to record large files too.";
        };
        bundleMiB = lib.mkOption {
          type = lib.types.ints.positive;
          default = 1024;
          description = "Largest Git bundle a manager may receive from one worker, in MiB; the broker streams it without retaining it as a whole.";
        };
        holdDays = lib.mkOption {
          type = lib.types.ints.positive;
          default = 14;
          description = "How long a removed worker's folder is kept, unmounted, before the system destroys it; it can be restored until then.";
        };
        roleFiles = lib.mkOption {
          type = lib.types.attrsOf lib.types.path;
          default = lib.genAttrs roles (role: "${inputs.nixos-secrets}/pi/roles/${role}.md");
          defaultText = lib.literalMD "`pi/roles/<role>.md` of the nixos-secrets input, for each of the four roles";
          description = "Per role, the file with the instructions that every worker of that role gets. The texts are the user's own: private, not secret.";
        };
        sandbox = lib.mkOption {
          type = lib.types.raw;
          readOnly = true;
          description = "What the pi launcher applies to every sandbox (mkSandbox's workers argument).";
        };
      };

      config = {
        hostSpec.workers.sandbox = {
          helper = if zfs then "/run/wrappers/bin/sudo -n ${helper}/bin/worker-datasets" else null;
          tmpfsBytes = lib.mapAttrs (_: size: size * 1024 * 1024) cfg.tmpfsMiB;
          inherit (cfg) agentMemory;
          start = "${start}";
          startSpec = lib.concatStringsSep " " startSpecCommand;
          supervise = "${python} ${checked ../../workers/supervise.py}";
          prepare = "${prepareCopy}/bin/prepare-copy";
          readChecked = "${python} ${checked ../../workers/read-checked.py}";
          # Says whether an implementer's copy is writable at this start: open, no approval, or no baseline
          lockState = "${lib.concatStringsSep " " approveCommand} --state";
          inherit (cfg) roleFiles;
          # A task file becomes part of the system prompt
          maxTaskBytes = maxTextBytes;
          # An ordinary session's run records are in the home, outside every dataset limit: beyond this size one older file is kept
          maxPlainRecordBytes = 1024 * 1024;
        };

        assertions = [
          {
            assertion = (cfg.timingCpus == "") == (cfg.workCpus == "");
            message = "hostSpec.workers: timingCpus and workCpus are set together or not at all";
          }
          # Refuse a missing text instead of starting workers of that role without their instructions
          {
            assertion =
              lib.sort lib.lessThan (lib.attrNames cfg.roleFiles) == lib.sort lib.lessThan roles
              && lib.all builtins.pathExists (lib.attrValues cfg.roleFiles);
            message = "hostSpec.workers.roleFiles needs an existing file for each of ${lib.concatStringsSep ", " roles}. The default is pi/roles/<role>.md of the nixos-secrets input: update its pin with 'config update secrets'";
          }
        ];

        environment.systemPackages = [
          queue
          workerRead
          workerBundle
          intent
          workersTool
        ];

        # A removed worker's folder is destroyed by this timer alone, once its mark is older than the holding time
        systemd.services.worker-datasets-expire = lib.mkIf zfs {
          description = "Destroy the folders of workers that were removed long enough ago";
          unitConfig.RequiresMountsFor = [
            workersPath
            scratchPath
          ];
          serviceConfig = {
            Type = "oneshot";
            ExecStart = "${helper}/bin/worker-datasets expire";
          };
        };
        systemd.timers.worker-datasets-expire = lib.mkIf zfs {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnCalendar = "daily";
            Persistent = true;
          };
        };

        systemd.tmpfiles.rules = [
          "d /run/worker-queue 0555 root root -"
        ]
        ++ map (name: "f /run/worker-queue/${name} 0444 root root -") lockFiles;

        # The resource groups, in the user's systemd. The limits of an agent's own scope and of a broker are set when they start
        systemd.user.slices = {
          workers.sliceConfig = {
            MemoryMax = cfg.totalMemory;
            MemorySwapMax = 0;
            CPUWeight = cfg.processorWeight;
          };
          workers-agents.sliceConfig = {
            MemoryMax = cfg.agentsMemory;
            CPUQuota = cfg.agentsCpuQuota;
          };
          workers-jobs.sliceConfig = { };
          workers-timing.sliceConfig = lib.mkIf (cfg.timingCpus != "") { AllowedCPUs = cfg.timingCpus; };
          workers-brokers.sliceConfig = { };
        };
        # The user's systemd may say which CPUs its slices use; without this it has memory and processor time only
        systemd.services."user@" = {
          overrideStrategy = "asDropin";
          serviceConfig.Delegate = "cpu cpuset io memory pids";
        };

        # A build started from a sandbox runs in the Nix daemon, outside every limit above, and the daemon cannot tell workers apart:
        # all builds are kept off the timing cores, behind interactive work, and inside a memory limit
        systemd.services.nix-daemon.serviceConfig = {
          CPUWeight = 20;
          MemoryMax = cfg.nixDaemonMemory;
        }
        // lib.optionalAttrs (cfg.workCpus != "") { AllowedCPUs = cfg.workCpus; };

        # One watcher for all sandboxes and jobs: every process that the kernel stops for memory inside workers.slice is reported
        systemd.user.services.workers-memory-watch = {
          description = "Report worker processes that were stopped for memory";
          wantedBy = [ "default.target" ];
          path = [
            pkgs.coreutils
            pkgs.gawk
            pkgs.libnotify
            pkgs.util-linux
          ];
          script = ''
            events=/sys/fs/cgroup/user.slice/user-$UID.slice/user@$UID.service/workers.slice/memory.events
            reservation=$XDG_RUNTIME_DIR/workers/timing-reserved
            # Every stop is also written down for `workers status`: when, how many, and in which resource group if that still exists
            stops=$HOME/.local/state/workers/memory-stops.jsonl
            mkdir -p "$(dirname "$stops")"
            declare -A seen
            last=0
            reserved=0
            while sleep 2; do
              # The timing cores are reserved although no timing job runs: its broker ended before it gave them back
              if [ -e "$reservation" ] && flock -n /run/worker-queue/timing true; then
                reserved=$((reserved + 1))
                if [ "$reserved" = 3 ]; then
                  echo "the timing cores stay reserved although no timing job runs: everything else is kept off them until a timing job ends"
                  notify-send --urgency=normal "The timing cores stay reserved" "A timing job ended without giving them back. They are free again when the next timing job ends: queue timing -- true" \
                    || echo "the notification could not be shown on the desktop"
                fi
              else
                reserved=0
              fi
              # The slice exists while a sandbox runs; its counter starts again with it
              if [ ! -r "$events" ]; then
                last=0
                seen=()
                continue
              fi
              count=$(awk '$1 == "oom_kill" { print $2 }' "$events")
              # The groups of the agents and of the jobs, each with its own count; a job's group ends with the job, so a stop
              # in a job that ended within these two seconds is written down without its group
              named=0
              for file in "''${events%/memory.events}"/*/*/memory.events; do
                [ -r "$file" ] || continue
                unit=$(basename "$(dirname "$file")")
                now=$(awk '$1 == "oom_kill" { print $2 }' "$file") || continue
                before=''${seen[$unit]:-0}
                # A group of that name that was made anew counts from nothing again
                if [ "''${now:-0}" -lt "$before" ]; then before=0; fi
                if [ "''${now:-0}" -gt "$before" ]; then
                  printf '{"time": %s, "unit": "%s", "count": %s}\n' "$(date +%s)" "$unit" "$((now - before))" >> "$stops"
                  named=$((named + now - before))
                fi
                seen[$unit]=''${now:-0}
              done
              if [ "$((count - last))" -gt "$named" ]; then
                printf '{"time": %s, "count": %s}\n' "$(date +%s)" "$((count - last - named))" >> "$stops"
              fi
              if [ "$count" -gt "$last" ]; then
                echo "$((count - last)) worker process(es) stopped for memory: the workers reached a memory limit"
                notify-send --urgency=critical "A worker process was stopped for memory" "The workers reached a memory limit. Details: journalctl --user -u workers-memory-watch" \
                  || echo "the notification could not be shown on the desktop"
              fi
              last=$count
            done
          '';
        };

        # Once a week: if there are workers whose work is merged and that can be removed, say so on the desktop, with the space
        # they hold. Nothing is removed by it; the command is the user's (workers remove --merged <project>)
        systemd.user.services.workers-reminder = {
          description = "Remind of workers that can be removed";
          path = [ pkgs.libnotify ];
          serviceConfig.Type = "oneshot";
          script = ''
            sentence=$(${workersTool}/bin/workers status --reminder)
            if [ -n "$sentence" ]; then
              echo "$sentence"
              notify-send --urgency=low "Workers that can be removed" "$sentence" || echo "the notification could not be shown on the desktop"
            fi
          '';
        };
        systemd.user.timers.workers-reminder = {
          description = "Weekly reminder of workers that can be removed";
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnCalendar = "Mon 09:00";
            Persistent = true;
          };
        };

        # The user may run the helper, and only it, as root without a password. A sandbox has no working sudo
        security.sudo.extraRules = lib.mkIf zfs [
          {
            users = [ cfg.user ];
            commands = [
              {
                command = "${helper}/bin/worker-datasets";
                options = [ "NOPASSWD" ];
              }
            ];
          }
        ];

        # The workers' datasets carry their own mount points and are mounted after the two parents, at boot and whenever a worker starts
        systemd.services.worker-datasets-mount = lib.mkIf zfs {
          description = "Mount the workers' folders and scratch areas";
          wantedBy = [ "multi-user.target" ];
          unitConfig.RequiresMountsFor = [
            workersPath
            scratchPath
          ];
          # Without it the workers' folders are missing, also from the backup: say so on the desktop, as a failed backup does
          onFailure = [ "worker-datasets-mount-failed.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
            ExecStart = "${helper}/bin/worker-datasets mount-all";
          };
        };
        systemd.services.worker-datasets-mount-failed = lib.mkIf zfs {
          description = "Report on the desktop that the workers' folders are not mounted";
          serviceConfig = {
            Type = "oneshot";
            ExecStart = lib.concatStringsSep " " [
              "${pkgs.dbus}/bin/dbus-send --system / net.nuetzlich.SystemNotifications.Notify"
              ''"string:Workers' folders not mounted"''
              ''"string:The folders of the agent workers could not be mounted; they are also missing from the backup. Details: journalctl -u worker-datasets-mount.service"''
            ];
          };
        };
        services.systembus-notify.enable = lib.mkIf zfs true;
      };
    };

  perSystem =
    { pkgs, ... }:
    let
      inherit (pkgs) lib;
      # The roles' real texts are the user's own and private; the checks use these in their place, and test for them
      standInRoles = lib.genAttrs roles (
        role: pkgs.writeText "worker-role-${role}.md" "Your role in this session is ${role}.\n"
      );
      # The laptop's layout is the one definition of the parents: the test machine gets the same datasets, mounts, owners and snapshot rule from it
      laptop = topLevel.flake.nixosConfigurations.mimir.config;
      user = laptop.hostSpec.disk.scratchUser;
      declared = lib.filterAttrs (
        name: _:
        builtins.elem name [
          "scratch"
          "scratch/workers"
          "workers"
        ]
      ) laptop.disko.devices.zpool.rpool.datasets;

      # The real pi, as this flake builds it, for the one test that starts it in every role
      realPi = pkgs.pi-coding-agent;
      # A deterministic continuation failure after the first real interactive session, to check the manual recovery path
      restartFailurePi = pkgs.writeShellScript "pi-restart-failure-probe" ''
        for argument in "$@"; do
          if [ "$argument" = -c ]; then
            echo "forced continuation failure" >&2
            exit 9
          fi
        done
        exec ${realPi}/bin/pi "$@"
      '';

      standIn =
        config:
        topLevel.flake.lib.mkSandbox pkgs {
          name = "worker-shell";
          command = "${pkgs.bash}/bin/bash";
          workers = config.hostSpec.workers.sandbox;
        };
      # The dashboard's program (workers-dashboard/), whose reader judges the status document in two of the checks (W13)
      # Built without a status command: the checks give it the document as a file
      watchProgram = "${import ../../workers-dashboard/package.nix pkgs { }}/bin/workers-watch";
      # Kept outside the already near-limit VM script, but checked independently before that script can load it
      bundleTestProgram =
        pkgs.runCommand "test-bundle.py" { nativeBuildInputs = [ pkgs.python3Packages.pyflakes ]; }
          ''
            pyflakes ${../../workers/test-bundle.py}
            cp ${../../workers/test-bundle.py} "$out"
          '';
      # Inside a build on a host without hardware virtualisation the test machines are emulated and many times slower; the
      # test driver's own limit of an hour is too short there
      emulatedTimeout = 6 * 3600;
    in
    {
      # The dashboard's own tests: both of its builds, and its reader against good and hostile status documents
      checks.workers-watch = (import ../../workers-dashboard/checks.nix pkgs).workers-watch;

      # The queue and the resource groups in a virtual machine, with stand-in workers on plain folders
      # Run it with KVM, outside the Nix sandbox: nix build .#checks.x86_64-linux.workers-queue.driver && ./result/bin/nixos-test-driver
      checks.workers-queue = pkgs.testers.runNixOSTest {
        name = "workers-queue";
        skipTypeCheck = true;
        nodes.machine =
          { config, pkgs, ... }:
          {
            imports = [ topLevel.flake.modules.nixos.workers ];
            virtualisation = {
              memorySize = 3072;
              cores = 4;
              # Room for the kept copy of 2 GiB of output
              diskSize = 6144;
            };
            # NixOS test machines panic on every out-of-memory kill, also one inside a memory limit; a normal system (0) does not
            boot.kernel.sysctl."vm.panic_on_oom" = 0;
            users.users.${user} = {
              isNormalUser = true;
              uid = 1000;
              linger = true;
            };
            # Two slots, one parallel token, one timing core, and limits small enough to reach
            hostSpec.workers = {
              inherit user;
              roleFiles = standInRoles;
              slots = 2;
              maxSlots = 1;
              jobProcessors = 1;
              timingCpus = "0";
              workCpus = "1-3";
              totalMemory = "640M";
              agentsMemory = "384M";
              agentMemory = "256M";
              agentsCpuQuota = "150%";
              processorWeight = 20;
              tmpfsMiB = {
                tmp = 64;
                home = 32;
                run = 8;
                shm = 16;
              };
            };
            environment.systemPackages = [
              (standIn config)
              pkgs.git
              pkgs.python3
            ];
          };
        globalTimeout = emulatedTimeout;
        testScript = ''
          user = "${user}"
        ''
        + builtins.readFile ../../workers/test-queue.py;
      };

      # The git paths in a virtual machine, on plain folders: copies, merging in the manager's copy, what the user takes, hostile copies
      # Run it with KVM, outside the Nix sandbox: nix build .#checks.x86_64-linux.workers-git.driver && ./result/bin/nixos-test-driver
      checks.workers-git = pkgs.testers.runNixOSTest {
        name = "workers-git";
        skipTypeCheck = true;
        nodes.machine =
          { config, pkgs, ... }:
          {
            imports = [ topLevel.flake.modules.nixos.workers ];
            users.users.${user} = {
              isNormalUser = true;
              uid = 1000;
              linger = true;
            };
            hostSpec.workers = {
              inherit user;
              roleFiles = standInRoles;
              totalMemory = "1G";
              agentsMemory = "768M";
              agentMemory = "512M";
              # Short, so that the test reaches them
              questionSeconds = 15;
              maxRunSeconds.timing = 10;
              foundLargeMiB = 1;
            };
            environment.systemPackages = [
              (standIn config)
              # The launcher as a machine without the worker setup has it, for the test of nix inside a sandbox
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "plain-shell";
                command = "${pkgs.bash}/bin/bash";
              })
              # A launcher for which the repository ~/repos/guarded has a protected folder
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-shell-guarded";
                command = "${pkgs.bash}/bin/bash";
                workers = config.hostSpec.workers.sandbox;
                protected.guarded = [
                  "guarded"
                  "nested/deep/file"
                ];
              })
              # A launcher whose preparation step takes a few seconds, so that the test can look at where it runs
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-shell-slow";
                command = "${pkgs.bash}/bin/bash";
                workers = config.hostSpec.workers.sandbox // {
                  prepare = pkgs.writeShellScript "slow-prepare" ''
                    ${pkgs.coreutils}/bin/sleep 5
                    exec ${config.hostSpec.workers.sandbox.prepare} "$@"
                  '';
                };
              })
              pkgs.git
            ];
          };
        globalTimeout = emulatedTimeout;
        testScript = ''
          user = "${user}"
        ''
        + builtins.readFile ../../workers/test-git.py;
      };

      # Remembered worker starts in a focused virtual machine, on plain folders
      checks.workers-starts = pkgs.testers.runNixOSTest {
        name = "workers-starts";
        skipTypeCheck = true;
        nodes.machine =
          { config, pkgs, ... }:
          let
            # The worker command records which user or system profile launcher ran, what Pi receives, and the two share modes
            commandProbe =
              profile:
              pkgs.writeShellScript "worker-start-command-${profile}-probe" ''
                echo ${lib.escapeShellArg profile} > "$WORKER_SCRATCH/pi-launcher"
                : > "$WORKER_SCRATCH/pi-arguments"
                for argument in "$@"; do printf '%s\n' "$argument" >> "$WORKER_SCRATCH/pi-arguments"; done
                if ${pkgs.coreutils}/bin/touch ${lib.escapeShellArg "/home/${user}/shared data/read only/from-worker"} 2> /dev/null; then
                  echo writable
                else
                  echo read-only
                fi > "$WORKER_SCRATCH/share-modes"
                if (printf written > ${lib.escapeShellArg "/home/${user}/shared data/write space/from-worker"}) 2> /dev/null; then
                  echo writable
                else
                  echo read-only
                fi >> "$WORKER_SCRATCH/share-modes"
              '';
            # The host-side start hook proves a remembered command exists before the sandbox command executes
            startProbe = pkgs.writeShellScript "worker-start-before-probe" ''
              case "$WORKER_UNIT" in
                worker:*)
                  id=''${WORKER_UNIT#worker:}
                  id=''${id//:/\/}
                  /run/current-system/sw/bin/workers command "$id" > "/tmp/start-before-''${id//\//-}"
                  ;;
              esac
              exec ${config.hostSpec.workers.sandbox.start} "$@"
            '';
            piProbe =
              profile:
              topLevel.flake.lib.mkSandbox pkgs {
                name = "pi";
                command = "${commandProbe profile}";
                workers = config.hostSpec.workers.sandbox // {
                  start = "${startProbe}";
                };
                protected.guarded = [ "protected" ];
              };
          in
          {
            imports = [ topLevel.flake.modules.nixos.workers ];
            users.users.${user} = {
              isNormalUser = true;
              uid = 1000;
              linger = true;
              packages = [ (piProbe "user-profile") ];
            };
            hostSpec.workers = {
              inherit user;
              roleFiles = standInRoles;
              totalMemory = "1G";
              agentsMemory = "768M";
              agentMemory = "512M";
            };
            environment.systemPackages = [
              (piProbe "system-profile")
              pkgs.git
            ];
          };
        globalTimeout = emulatedTimeout;
        testScript = ''
          user = "${user}"
        ''
        + builtins.readFile ../../workers/test-starts.py;
      };

      # The roles and the start-up checks in a virtual machine, on plain folders
      # Run it with KVM, outside the Nix sandbox: nix build .#checks.x86_64-linux.workers-roles.driver && ./result/bin/nixos-test-driver
      checks.workers-roles = pkgs.testers.runNixOSTest {
        name = "workers-roles";
        skipTypeCheck = true;
        nodes.machine =
          { config, pkgs, ... }:
          let
            # Stands in for pi: a command that takes instruction files. It prints what it was started with, and the task once more after a wait
            printArguments = pkgs.writeShellScript "print-arguments" ''
              echo "folder: $PWD"
              ${pkgs.coreutils}/bin/ls -A | ${pkgs.gnused}/bin/sed 's/^/    in the folder: /'
              for argument in "$@"; do
                echo "argument: $argument"
                if [ -f "$argument" ]; then ${pkgs.gnused}/bin/sed 's/^/    /' "$argument"; fi
              done
              # For a test that changes the task file meanwhile: go on when that file exists
              if [ -n "''${WAIT_FOR:-}" ]; then
                until [ -e "$WAIT_FOR" ]; do ${pkgs.coreutils}/bin/sleep 0.2; done
                echo "the task afterwards:"
                ${pkgs.coreutils}/bin/cat /run/task.md
              fi
            '';
            controlProbe = pkgs.writeShellScript "control-probe" ''
              result=$WORKER_SCRATCH/control-probe-result
              attempt() {
                label=$1
                shift
                if "$@" 2> /dev/null; then state=written; else state=refused; fi
                printf '%s=%s\n' "$label" "$state" >> "$result"
              }
              : > "$result"
              attempt started ${pkgs.coreutils}/bin/dd if=/dev/zero of=/run/worker-control/started bs=1M count=8 status=none
              attempt mode ${pkgs.bash}/bin/bash -c 'printf changed > /run/worker-control/mode'
              attempt create ${pkgs.bash}/bin/bash -c 'printf created > /run/worker-control/created'
              touch "$WORKER_SCRATCH/control-probe-ready"
              until [ -e "$WORKER_SCRATCH/control-probe-stop" ]; do ${pkgs.coreutils}/bin/sleep 0.05; done
            '';
          in
          {
            imports = [ topLevel.flake.modules.nixos.workers ];
            # No way out of the machine: the one test that starts pi itself must not reach a provider
            virtualisation.restrictNetwork = true;
            users.users.${user} = {
              isNormalUser = true;
              uid = 1000;
              linger = true;
            };
            hostSpec.workers = {
              inherit user;
              roleFiles = standInRoles;
              totalMemory = "1G";
              agentsMemory = "768M";
              agentMemory = "512M";
              # Small only in this VM, so the bundle refusal is practical to reach
              bundleMiB = 1;
            };
            environment.systemPackages = [
              (standIn config)
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-args";
                command = "${printArguments}";
                workers = config.hostSpec.workers.sandbox;
                promptOption = "--instructions";
              })
              # pi itself, without a network: it gets as far as its first request
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-pi";
                command = "${realPi}/bin/pi";
                workers = config.hostSpec.workers.sandbox;
                promptOption = "--append-system-prompt";
                environment = {
                  PI_OFFLINE = "1";
                  PI_SKIP_VERSION_CHECK = "1";
                  PI_TELEMETRY = "0";
                };
              })
              # A deterministic sandbox command that probes the approval control mount without depending on pi startup
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-control-probe";
                command = "${controlProbe}";
                workers = config.hostSpec.workers.sandbox;
                promptOption = "--instructions";
                approvalRestart = ../../workers/approval-restart.ts;
              })
              # Real interactive pi with a local deterministic provider, for the automatic approval continuation
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-pi-restart";
                command = "${realPi}/bin/pi --extension ${../../workers/test-provider.ts} --provider worker-test --model deterministic --offline";
                workers = config.hostSpec.workers.sandbox;
                promptOption = "--append-system-prompt";
                approvalRestart = ../../workers/approval-restart.ts;
                environment = {
                  PI_SKIP_VERSION_CHECK = "1";
                  PI_TELEMETRY = "0";
                };
              })
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-pi-restart-failure";
                command = "${restartFailurePi} --extension ${../../workers/test-provider.ts} --provider worker-test --model deterministic --offline";
                workers = config.hostSpec.workers.sandbox;
                promptOption = "--append-system-prompt";
                approvalRestart = ../../workers/approval-restart.ts;
                environment = {
                  PI_SKIP_VERSION_CHECK = "1";
                  PI_TELEMETRY = "0";
                };
              })
              # Direct access to the production supervisor for bounded-channel lifecycle controls
              (pkgs.writeShellScriptBin "worker-supervise-test" ''
                exec ${config.hostSpec.workers.sandbox.supervise} "$@"
              '')
              # Tools of a development shell, for the same test
              pkgs.expect
              pkgs.python3
              pkgs.uv
              pkgs.gcc
              pkgs.gnumake
              pkgs.openmpi
              # A shell whose ordinary sessions keep few records, so that the test reaches the limit
              (topLevel.flake.lib.mkSandbox pkgs {
                name = "worker-shell-small";
                command = "${pkgs.bash}/bin/bash";
                workers = config.hostSpec.workers.sandbox // {
                  maxPlainRecordBytes = 600;
                };
              })
              pkgs.git
            ];
          };
        globalTimeout = emulatedTimeout;
        testScript = ''
          user = "${user}"
          watchProgram = "${watchProgram}"
          bundleTest = "${bundleTestProgram}"
          # A session file with entries of the to-do extension, as `workers status` reads them
          sampleSession = ${builtins.toJSON (builtins.readFile ../../workers/sample-session.jsonl)}
        ''
        + builtins.readFile ../../workers/test-roles.py;
      };

      # The layout in two virtual machines, with stand-in workers: the pi launcher running a shell
      # Run it with KVM, outside the Nix sandbox: nix build .#checks.x86_64-linux.workers-layout.driver && ./result/bin/nixos-test-driver
      checks.workers-layout = pkgs.testers.runNixOSTest {
        name = "workers-layout";
        # The script is plain Python without annotations
        skipTypeCheck = true;
        nodes.machine =
          {
            config,
            pkgs,
            utils,
            ...
          }:
          {
            imports = [ topLevel.flake.modules.nixos.workers ];
            virtualisation = {
              memorySize = 2048;
              cores = 2;
              # The pool; the test creates the declared datasets on it at the first boot, the system mounts them at the second
              emptyDiskImages = [ 4096 ];
              # (virtualisation.fileSystems: a test machine ignores fileSystems)
              fileSystems = lib.mapAttrs' (
                name: dataset:
                lib.nameValuePair dataset.mountpoint {
                  device = "rpool/${name}";
                  fsType = "zfs";
                  options = [ "nofail" ];
                }
              ) declared;
            };
            networking.hostId = "8425e349";
            boot.supportedFilesystems = [ "zfs" ];
            boot.zfs.forceImportRoot = false;
            # A virtual disk has no /dev/disk/by-id entry
            boot.zfs.devNodes = "/dev/disk/by-path";
            # NixOS test machines panic on every out-of-memory kill; a normal system (0) does not
            boot.kernel.sysctl."vm.panic_on_oom" = 0;
            users.users.${user} = {
              isNormalUser = true;
              uid = 1000;
              # The user's systemd runs without a login, as it does in a desktop session
              linger = true;
              # As on the laptop: sudo asks members of wheel for their password, except for the helper
              extraGroups = [ "wheel" ];
            };
            # The owners of the three top folders, as on the laptop
            systemd.tmpfiles.rules = builtins.filter (lib.hasInfix "/home/${user}/") laptop.systemd.tmpfiles.rules;
            # On the laptop these mounts are required, which orders them before the folders' owners are set. Here they are optional,
            # because the pool does not exist at the first boot, so the order is stated: without it the owner is sometimes set on the
            # folder underneath the mount
            systemd.services.systemd-tmpfiles-setup.after = map (
              dataset: "${utils.escapeSystemdPath dataset.mountpoint}.mount"
            ) (builtins.attrValues declared);
            # The laptop's snapshot rule for the workers
            services.sanoid = {
              enable = true;
              templates.workers = lib.filterAttrs (
                _: value: value != null
              ) laptop.services.sanoid.templates.workers;
              datasets."rpool/workers" = {
                inherit (laptop.services.sanoid.datasets."rpool/workers") useTemplate recursive;
              };
            };
            # Small limits, so that the test reaches them
            hostSpec.workers = {
              inherit user;
              roleFiles = standInRoles;
              folderQuota = "64M";
              areaQuota = "96M";
              instructionsQuota = "16M";
              tmpfsMiB = {
                tmp = 32;
                home = 16;
                run = 8;
                shm = 16;
              };
              totalMemory = "1G";
              agentsMemory = "768M";
              agentMemory = "512M";
            };
            environment.systemPackages = [
              (standIn config)
              pkgs.git
            ];
          };
        # Without ZFS: plain folders, as on the test VM of the desktop
        nodes.plain =
          { config, pkgs, ... }:
          {
            imports = [ topLevel.flake.modules.nixos.workers ];
            users.users.${user} = {
              isNormalUser = true;
              uid = 1000;
              linger = true;
            };
            hostSpec.workers = {
              inherit user;
              roleFiles = standInRoles;
              totalMemory = "1G";
              agentsMemory = "768M";
              agentMemory = "512M";
            };
            environment.systemPackages = [
              (standIn config)
              pkgs.git
            ];
          };
        globalTimeout = emulatedTimeout;
        testScript = ''
          user = "${user}"
          watchProgram = "${watchProgram}"
          # zfs create for each declared dataset, with its declared options
          create = ${
            builtins.toJSON (
              lib.mapAttrsToList (
                name: dataset:
                "zfs create ${
                  lib.concatStringsSep " " (lib.mapAttrsToList (key: value: "-o ${key}=${value}") dataset.options)
                } rpool/${name}"
              ) declared
            )
          }
          mounts = ${
            builtins.toJSON (lib.mapAttrsToList (name: dataset: "${dataset.mountpoint} rpool/${name}") declared)
          }
          # How the laptop's backup finds the workers' file systems
          backupList = ${builtins.toJSON (laptop.services.restic.backups.home.dynamicFilesFrom or "")}
        ''
        + builtins.readFile ../../workers/test-layout.py;
      };
    };
}
