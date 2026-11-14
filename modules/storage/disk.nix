# Encrypted ZFS disk layout
#
# What it is    EFI, random-key swap and a LUKS-encrypted ZFS pool with quotas and snapshots
# Who uses it   A physical NixOS host by importing nixos.disk and filling hostSpec.disk
# A host adds   Its stable disk path, scratch owner and sizes chosen for that disk
# Protected     Yes: applying this layout erases a disk and a wrong change can lose data (docs/DISK.md)
{ inputs, config, ... }:
let
  # Keep the named disk and boot modules available for the install test below
  topLevel = config;
in
{
  flake.modules.nixos.disk =
    { config, lib, ... }:
    let
      ## Part 1. Host values and reusable dataset shape
      # Use one short name for the host-specific disk choices
      cfg = config.hostSpec.disk;

      # Look up the account that owns the writable scratch dataset
      scratchOwner = config.users.users.${cfg.scratchUser};
      # Build this path directly because accounts and file systems depend on each other during evaluation
      scratchPath = "/home/${cfg.scratchUser}/scratch";
      # Keep worker copies and raw worker output below root-owned top folders
      # This prevents user processes from renaming or replacing the mount points
      workersPath = "/home/${cfg.scratchUser}/workers";
      workersScratchPath = "${scratchPath}/workers";

      # Use legacy mount points so NixOS orders every ZFS dataset through fileSystems
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
      # Add disko's declarative disk and installation scripts
      imports = [ inputs.disko.nixosModules.disko ];

      ## Part 2. Values every host must choose
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
        # Require host-specific capacities because safe limits depend on the physical disk size
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
        # Refuse a scratch path that does not sit inside the chosen account's real home folder
        assertions = [
          {
            assertion = scratchOwner.home == "/home/${cfg.scratchUser}";
            message = "nixos.disk mounts the scratch dataset at ${scratchPath}, but the home folder of ${cfg.scratchUser} is ${scratchOwner.home}";
          }
        ];

        ## Part 3. Partitions, encryption and datasets
        disko.devices = {
          disk.main = {
            type = "disk";
            inherit (cfg) device;
            content = {
              type = "gpt";
              partitions = {
                # Reserve a private UEFI system partition for boot files
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
                # Use a fresh random swap key each boot because hibernation is deliberately unavailable
                swap = {
                  size = cfg.swapSize;
                  content = {
                    type = "swap";
                    randomEncryption = true;
                  };
                };
                # Give all remaining space to one encrypted container holding the ZFS pool
                luks = {
                  size = "100%";
                  content = {
                    type = "luks";
                    name = "crypt";
                    inherit (cfg) passwordFile;
                    # Pass discard information through encryption so SSD TRIM still works
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
              # Align ZFS writes to 4 KiB sectors
              ashift = "12";
              # Return unused blocks to the SSD automatically
              autotrim = "on";
            };
            # Apply space-saving and Linux-compatible defaults to every child dataset
            rootFsOptions = {
              mountpoint = "none";
              canmount = "off";
              compression = "zstd";
              atime = "off";
              xattr = "sa";
              acltype = "posixacl";
              dnodesize = "auto";
            };
            # Separate reproducible data, personal data, scratch output and agent work for independent limits
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

        ## Part 4. Mount order and ownership
        # Mount /home before account creation so home folders are created inside its dataset
        fileSystems."/home".neededForBoot = true;

        # Give scratch to its user while keeping both worker mount points owned by root
        systemd.tmpfiles.rules = [
          "d ${scratchPath} 0755 ${scratchOwner.name} ${scratchOwner.group} -"
          "d ${workersPath} 0755 root root -"
          "d ${workersScratchPath} 0755 root root -"
        ];

        # Never force-import a root pool that appears to belong to another active system
        boot.zfs.forceImportRoot = false;

        # Cap ZFS's slowly released cache at 4 GiB so simulations and agent workers retain memory
        boot.kernelParams = [ "zfs.zfs_arc_max=${toString (4 * 1024 * 1024 * 1024)}" ];

        ## Part 5. Disk maintenance and snapshots
        services.zfs = {
          # Read every block monthly so checksum errors are found while recovery is still possible
          autoScrub = {
            enable = true;
            interval = "monthly";
          };
          # Schedule explicit pool TRIM in addition to the pool's automatic setting
          trim.enable = true;
        };

        # Snapshot only data that cannot be recreated, excluding /nix and all scratch datasets
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
            # Retain worker snapshots for less time because fast-changing copies consume their quota quickly
            # Git and backup hold committed work; these snapshots only protect an agent's current copy
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
            # Cover every worker dataset created later below this one without adding another rule
            "rpool/workers" = {
              useTemplate = [ "workers" ];
              recursive = true;
            };
          };
        };
      };
    };

  ## Part 6. Full disk installation test
  perSystem =
    { pkgs, ... }:
    let
      # Let disko format empty virtual disks, install a minimal host and boot it from this layout
      testHost = inputs.nixpkgs.lib.nixosSystem {
        modules = [
          topLevel.flake.modules.nixos.disk
          topLevel.flake.modules.nixos.boot
          {
            # Use the same package set as the check runner
            nixpkgs.pkgs = pkgs;

            # Give the isolated test fixed identifiers that do not describe a real host
            networking.hostName = "disktest";
            networking.hostId = "8425e349";
            system.stateVersion = "26.05";
            # Provide the account whose home, scratch and worker permissions are tested
            users.users.tester = {
              isNormalUser = true;
              uid = 1000;
            };

            hostSpec.disk = {
              # Use disko's empty secondary virtual disk as the destructive target
              device = "/dev/vdb";

              # Fit swap and reservations inside the test's 4 GiB disks
              swapSize = "256M";
              # Supply a formatting key only; type the boot passphrase through the console below
              passwordFile = "/tmp/secret.key";
              scratchUser = "tester";

              # Keep the reservation small enough to fit; quota limits may be larger than current use
              scratchQuota = "1G";
              workersQuota = "512M";
              nixQuota = "3G";
              homeReservation = "256M";
            };

            disko.tests = {
              # Unlock the encrypted root disk at the boot prompt
              bootCommands = ''
                machine.wait_for_console_text("Please enter passphrase for disk")
                machine.send_console("secretsecret\n")
              '';
              extraChecks = ''
                ## Step 1. Check the healthy pool sits on the opened LUKS container
                machine.succeed("zpool status -x rpool | grep -q 'is healthy'")
                machine.succeed("cryptsetup isLuks /dev/disk/by-partlabel/disk-main-luks")
                machine.succeed("zpool status -LP rpool | grep -q \"$(readlink -f /dev/mapper/crypt)\"")

                ## Step 2. Check every dataset mount, compression and access-time setting
                for path, name in [("/", "rpool/root"), ("/nix", "rpool/nix"), ("/home", "rpool/home"), ("/home/tester/scratch", "rpool/scratch"), ("/home/tester/scratch/workers", "rpool/scratch/workers"), ("/home/tester/workers", "rpool/workers")]:
                    machine.succeed(f"test \"$(findmnt -n -o SOURCE {path})\" = {name}")
                    machine.succeed(f"test \"$(zfs get -H -o value compression {name})\" = zstd")
                    machine.succeed(f"test \"$(zfs get -H -o value atime {name})\" = off")

                ## Step 3. Check swap uses plain dm-crypt with a random key
                # Ask the device for its type because swapon reports only the kernel's /dev/dm-N name
                swap = machine.succeed("swapon --noheadings --show=NAME").strip()
                machine.succeed(f"test \"$(lsblk -n -o TYPE {swap})\" = crypt")
                machine.succeed(f"cryptsetup status \"$(dmsetup info -c --noheadings -o name {swap})\" | grep -q 'type: *PLAIN'")

                ## Step 4. Take a /home snapshot and restore a deleted file from it
                machine.succeed("test \"$(stat -c '%U %a' /home/tester)\" = 'tester 700'")
                machine.succeed("su tester -c 'echo precious > /home/tester/file'")
                # Wait for completion because the unit reports started before snapshots have finished
                machine.succeed("systemctl start --wait sanoid.service")
                snapshots = machine.succeed("zfs list -H -t snapshot -o name")
                print(snapshots)
                machine.succeed("zfs list -H -t snapshot -o name | grep -qE '^rpool/home@autosnap_.*_hourly$'")
                machine.succeed("zfs list -H -t snapshot -o name | grep -qE '^rpool/root@autosnap_.*_daily$'")
                machine.succeed("rm /home/tester/file")
                snapshot = machine.succeed("zfs list -H -t snapshot -o name rpool/home | grep _hourly | head -1 | cut -d@ -f2").strip()
                machine.succeed(f"test \"$(cat /home/.zfs/snapshot/{snapshot}/tester/file)\" = precious")

                ## Step 5. Check excluded snapshots, limits, reservation and scratch ownership
                machine.fail("zfs list -H -t snapshot -o name | grep -qE '^rpool/(scratch|scratch/workers|nix)@'")
                for name, prop, value in [("rpool/scratch", "quota", "1G"), ("rpool/workers", "quota", "512M"), ("rpool/nix", "quota", "3G"), ("rpool/home", "reservation", "256M")]:
                    machine.succeed(f"test \"$(zfs get -H -o value {prop} {name})\" = {value}")
                machine.succeed("su tester -c 'echo data > /home/tester/scratch/output'")

                ## Step 6. Check the 4 GiB cache cap and disk-maintenance timers
                machine.succeed("test \"$(cat /sys/module/zfs/parameters/zfs_arc_max)\" = 4294967296")
                machine.succeed("systemctl is-enabled zfs-scrub.timer zpool-trim.timer")

                ## Step 7. Check root owns and protects both worker mount points
                # Control that the same user can write in scratch and rename an ordinary folder
                for path in ["/home/tester/workers", "/home/tester/scratch/workers"]:
                    machine.succeed(f"test \"$(stat -c '%U %a' {path})\" = 'root 755'")
                    machine.fail(f"su tester -c 'mkdir {path}/project'")
                    machine.fail(f"su tester -c 'mv {path} {path}-moved'")
                    machine.succeed(f"test -d {path} && ! test -e {path}-moved")
                machine.succeed("su tester -c 'mkdir /home/tester/plain && mv /home/tester/plain /home/tester/plain-moved'")

                ## Step 8. Check recursive worker snapshots do not spread into scratch
                machine.succeed("zfs create -o canmount=off -o mountpoint=none rpool/workers/project && zfs create -o canmount=off -o mountpoint=none rpool/scratch/workers/project")
                # Remove sanoid's 20-minute dataset cache instead of waiting for the next hourly run
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
      # Publish disko's destructive install-and-boot test as the disk-layout check
      checks.disk-layout = testHost.config.system.build.installTest;
    };
}
