# Encrypted ZFS system disk with snapshots; hosts opt in by importing nixos.disk and setting hostSpec.disk
# Layout: EFI partition, swap with a random key per boot, and a LUKS container holding the ZFS pool rpool
# Each dataset and its snapshot policy are declared here, in one place
{ inputs, config, ... }:
let
  topLevel = config;
in
{
  flake.modules.nixos.disk =
    { config, lib, ... }:
    let
      cfg = config.hostSpec.disk;
      scratchOwner = config.users.users.${cfg.scratchUser};
      # Not read from the account: the list of accounts depends on the file systems, which depend on this path
      scratchPath = "/home/${cfg.scratchUser}/scratch";
      # The copies and the raw output of agent workers; both top folders belong to root, so that nothing running as the user can rename or replace what is mounted below them
      workersPath = "/home/${cfg.scratchUser}/workers";
      workersScratchPath = "${scratchPath}/workers";

      # Every dataset is mounted through fileSystems (legacy mountpoint), so NixOS orders the mounts
      dataset = mountpoint: options: {
        type = "zfs_fs";
        inherit mountpoint;
        options = {
          mountpoint = "legacy";
        }
        // options;
      };
    in
    {
      imports = [ inputs.disko.nixosModules.disko ];

      options.hostSpec.disk = {
        device = lib.mkOption {
          type = lib.types.str;
          example = "/dev/disk/by-id/nvme-Example_2TB_SERIAL";
          description = "The disk to install on, by its stable /dev/disk/by-id path. It has no default: the disk is erased when the layout is applied.";
        };
        swapSize = lib.mkOption {
          type = lib.types.str;
          default = "32G";
          description = "Size of the swap partition.";
        };
        passwordFile = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "File holding the disk passphrase while the disk is formatted. With null the passphrase is asked interactively. It is always asked interactively at boot.";
        };
        scratchUser = lib.mkOption {
          type = lib.types.str;
          description = "The user whose ~/scratch is the scratch dataset and whose ~/workers is the workers dataset.";
        };
        # The sizes have no defaults: they depend on the disk, so every host states them
        scratchQuota = lib.mkOption {
          type = lib.types.str;
          example = "800G";
          description = "Upper limit of the scratch dataset, the workers' areas in it included, so that simulation output cannot fill the pool.";
        };
        workersQuota = lib.mkOption {
          type = lib.types.str;
          example = "200G";
          description = "Upper limit of the workers dataset: the agent workers' copies of projects, their reports and sessions.";
        };
        nixQuota = lib.mkOption {
          type = lib.types.str;
          example = "300G";
          description = "Upper limit of the Nix store. A full store stops builds until a garbage collection and takes no space from the home.";
        };
        homeReservation = lib.mkOption {
          type = lib.types.str;
          example = "300G";
          description = "Space that is kept for /home whatever the other datasets fill. It must fit on the disk: the layout cannot be applied otherwise.";
        };
      };

      config = {
        assertions = [
          {
            assertion = scratchOwner.home == "/home/${cfg.scratchUser}";
            message = "nixos.disk mounts the scratch dataset at ${scratchPath}, but the home folder of ${cfg.scratchUser} is ${scratchOwner.home}";
          }
        ];

        disko.devices = {
          disk.main = {
            type = "disk";
            inherit (cfg) device;
            content = {
              type = "gpt";
              partitions = {
                ESP = {
                  size = "1G";
                  type = "EF00";
                  content = {
                    type = "filesystem";
                    format = "vfat";
                    mountpoint = "/boot";
                    mountOptions = [ "umask=0077" ];
                  };
                };
                # A new random key at every boot: nothing in swap survives a reboot, and there is no hibernation
                swap = {
                  size = cfg.swapSize;
                  content = {
                    type = "swap";
                    randomEncryption = true;
                  };
                };
                luks = {
                  size = "100%";
                  content = {
                    type = "luks";
                    name = "crypt";
                    inherit (cfg) passwordFile;
                    # TRIM reaches the SSD through the encryption layer
                    settings.allowDiscards = true;
                    content = {
                      type = "zfs";
                      pool = "rpool";
                    };
                  };
                };
              };
            };
          };

          zpool.rpool = {
            type = "zpool";
            options = {
              ashift = "12";
              autotrim = "on";
            };
            rootFsOptions = {
              mountpoint = "none";
              canmount = "off";
              compression = "zstd";
              atime = "off";
              xattr = "sa";
              acltype = "posixacl";
              dnodesize = "auto";
            };
            datasets = {
              root = dataset "/" { };
              nix = dataset "/nix" { quota = cfg.nixQuota; };
              home = dataset "/home" { reservation = cfg.homeReservation; };
              scratch = dataset scratchPath { quota = cfg.scratchQuota; };
              "scratch/workers" = dataset workersScratchPath { };
              workers = dataset workersPath { quota = cfg.workersQuota; };
            };
          };
        };

        # /home is mounted before users are created, so home folders are created in it and not underneath it
        fileSystems."/home".neededForBoot = true;

        # The mount point of a dataset belongs to root; the scratch folder belongs to its user, the two workers folders stay root's
        systemd.tmpfiles.rules = [
          "d ${scratchPath} 0755 ${scratchOwner.name} ${scratchOwner.group} -"
          "d ${workersPath} 0755 root root -"
          "d ${workersScratchPath} 0755 root root -"
        ];

        boot.zfs.forceImportRoot = false;
        # ZFS's cache gives memory back slowly; capped at 4 GiB so that simulations and agent workers keep the RAM
        boot.kernelParams = [ "zfs.zfs_arc_max=${toString (4 * 1024 * 1024 * 1024)}" ];

        services.zfs = {
          # Reads every block and verifies its checksum
          autoScrub = {
            enable = true;
            interval = "monthly";
          };
          trim.enable = true;
        };

        # Snapshots: only for data that cannot be recreated; none for /nix and scratch, the workers' areas in scratch included
        services.sanoid = {
          enable = true;
          templates = {
            home = {
              hourly = 48;
              daily = 30;
              monthly = 6;
              yearly = 0;
              autosnap = true;
              autoprune = true;
            };
            # Shorter than /home's: workers' copies change fast, and a snapshot keeps every deleted file against the dataset's limit
            # Committed work is in git and in the backup; these are the net under an agent that wrecks its own copy
            workers = {
              hourly = 24;
              daily = 7;
              monthly = 0;
              yearly = 0;
              autosnap = true;
              autoprune = true;
            };
            system = {
              hourly = 0;
              daily = 7;
              monthly = 0;
              yearly = 0;
              autosnap = true;
              autoprune = true;
            };
          };
          datasets = {
            "rpool/home".useTemplate = [ "home" ];
            "rpool/root".useTemplate = [ "system" ];
            # Recursive: the dataset of every worker, created later below this one, is covered without a rule of its own
            "rpool/workers" = {
              useTemplate = [ "workers" ];
              recursive = true;
            };
          };
        };
      };
    };

  perSystem =
    { pkgs, ... }:
    let
      # A minimal system on this layout; disko's install test formats empty virtual disks with it, installs, and boots from them
      testHost = inputs.nixpkgs.lib.nixosSystem {
        modules = [
          topLevel.flake.modules.nixos.disk
          topLevel.flake.modules.nixos.boot
          {
            nixpkgs.pkgs = pkgs;
            networking.hostName = "disktest";
            networking.hostId = "8425e349";
            system.stateVersion = "26.05";
            users.users.tester = {
              isNormalUser = true;
              uid = 1000;
            };

            hostSpec.disk = {
              device = "/dev/vdb";
              # The test disks are 4 GiB
              swapSize = "256M";
              # Only for formatting; at boot the passphrase is typed on the console below
              passwordFile = "/tmp/secret.key";
              scratchUser = "tester";
              # Small enough for the test disks; the reservation must fit, the limits need not
              scratchQuota = "1G";
              workersQuota = "512M";
              nixQuota = "3G";
              homeReservation = "256M";
            };

            disko.tests = {
              bootCommands = ''
                machine.wait_for_console_text("Please enter passphrase for disk")
                machine.send_console("secretsecret\n")
              '';
              extraChecks = ''
                # 1. The pool is healthy and sits on the opened LUKS container
                machine.succeed("zpool status -x rpool | grep -q 'is healthy'")
                machine.succeed("cryptsetup isLuks /dev/disk/by-partlabel/disk-main-luks")
                machine.succeed("zpool status -LP rpool | grep -q \"$(readlink -f /dev/mapper/crypt)\"")

                # 2. The six datasets are mounted, compressed, without access-time updates
                for path, name in [("/", "rpool/root"), ("/nix", "rpool/nix"), ("/home", "rpool/home"), ("/home/tester/scratch", "rpool/scratch"), ("/home/tester/scratch/workers", "rpool/scratch/workers"), ("/home/tester/workers", "rpool/workers")]:
                    machine.succeed(f"test \"$(findmnt -n -o SOURCE {path})\" = {name}")
                    machine.succeed(f"test \"$(zfs get -H -o value compression {name})\" = zstd")
                    machine.succeed(f"test \"$(zfs get -H -o value atime {name})\" = off")

                # 3. Swap is active on a plain dm-crypt device with a random key
                # swapon reports the kernel name (/dev/dm-N), so the device itself is asked for its type and mapping name
                swap = machine.succeed("swapon --noheadings --show=NAME").strip()
                machine.succeed(f"test \"$(lsblk -n -o TYPE {swap})\" = crypt")
                machine.succeed(f"cryptsetup status \"$(dmsetup info -c --noheadings -o name {swap})\" | grep -q 'type: *PLAIN'")

                # 4. A snapshot of /home is taken, and a deleted file is restored from it
                machine.succeed("test \"$(stat -c '%U %a' /home/tester)\" = 'tester 700'")
                machine.succeed("su tester -c 'echo precious > /home/tester/file'")
                # --wait: the unit only reports "started", the snapshots are taken while it runs
                machine.succeed("systemctl start --wait sanoid.service")
                snapshots = machine.succeed("zfs list -H -t snapshot -o name")
                print(snapshots)
                machine.succeed("zfs list -H -t snapshot -o name | grep -qE '^rpool/home@autosnap_.*_hourly$'")
                machine.succeed("zfs list -H -t snapshot -o name | grep -qE '^rpool/root@autosnap_.*_daily$'")
                machine.succeed("rm /home/tester/file")
                snapshot = machine.succeed("zfs list -H -t snapshot -o name rpool/home | grep _hourly | head -1 | cut -d@ -f2").strip()
                machine.succeed(f"test \"$(cat /home/.zfs/snapshot/{snapshot}/tester/file)\" = precious")

                # 5. Scratch and /nix have no snapshots; the limits and the reservation are set; scratch belongs to its user
                machine.fail("zfs list -H -t snapshot -o name | grep -qE '^rpool/(scratch|scratch/workers|nix)@'")
                for name, prop, value in [("rpool/scratch", "quota", "1G"), ("rpool/workers", "quota", "512M"), ("rpool/nix", "quota", "3G"), ("rpool/home", "reservation", "256M")]:
                    machine.succeed(f"test \"$(zfs get -H -o value {prop} {name})\" = {value}")
                machine.succeed("su tester -c 'echo data > /home/tester/scratch/output'")

                # 6. The cache is capped at 4 GiB; scrub and TRIM are scheduled
                machine.succeed("test \"$(cat /sys/module/zfs/parameters/zfs_arc_max)\" = 4294967296")
                machine.succeed("systemctl is-enabled zfs-scrub.timer zpool-trim.timer")

                # 7. The two workers folders belong to root: the user can neither create something in them nor rename them
                # Control: the same user can write in ~/scratch (step 5) and rename an ordinary folder of his own
                for path in ["/home/tester/workers", "/home/tester/scratch/workers"]:
                    machine.succeed(f"test \"$(stat -c '%U %a' {path})\" = 'root 755'")
                    machine.fail(f"su tester -c 'mkdir {path}/project'")
                    machine.fail(f"su tester -c 'mv {path} {path}-moved'")
                    machine.succeed(f"test -d {path} && ! test -e {path}-moved")
                machine.succeed("su tester -c 'mkdir /home/tester/plain && mv /home/tester/plain /home/tester/plain-moved'")

                # 8. A dataset created later below the workers dataset gets snapshots without a rule of its own; one below scratch does not
                machine.succeed("zfs create -o canmount=off -o mountpoint=none rpool/workers/project && zfs create -o canmount=off -o mountpoint=none rpool/scratch/workers/project")
                # sanoid remembers its list of datasets for 20 minutes, less than the hour between its runs; the test forgets it instead of waiting
                machine.succeed("rm /var/cache/private/sanoid/datasets.txt")
                machine.succeed("systemctl start --wait sanoid.service")
                machine.succeed("zfs list -H -t snapshot -o name | grep -qE '^rpool/workers@autosnap_.*_hourly$'")
                machine.succeed("zfs list -H -t snapshot -o name | grep -qE '^rpool/workers/project@autosnap_.*_hourly$'")
                machine.fail("zfs list -H -t snapshot -o name | grep -qE '^rpool/scratch'")
              '';
            };
          }
        ];
      };
    in
    {
      checks.disk-layout = testHost.config.system.build.installTest;
    };
}
