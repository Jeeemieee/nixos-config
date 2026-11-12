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
          description = "The user whose ~/scratch is the scratch dataset.";
        };
        scratchQuota = lib.mkOption {
          type = lib.types.str;
          default = "1T";
          description = "Upper limit of the scratch dataset, so that simulation output cannot fill the pool.";
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
              nix = dataset "/nix" { };
              home = dataset "/home" { };
              scratch = dataset scratchPath { quota = cfg.scratchQuota; };
            };
          };
        };

        # /home is mounted before users are created, so home folders are created in it and not underneath it
        fileSystems."/home".neededForBoot = true;

        # The mount point of a dataset belongs to root; the scratch folder belongs to its user
        systemd.tmpfiles.rules = [
          "d ${scratchPath} 0755 ${scratchOwner.name} ${scratchOwner.group} -"
        ];

        boot.zfs.forceImportRoot = false;
        # ZFS's cache gives memory back slowly; capped at 8 GiB so that simulations keep the RAM
        boot.kernelParams = [ "zfs.zfs_arc_max=${toString (8 * 1024 * 1024 * 1024)}" ];

        services.zfs = {
          # Reads every block and verifies its checksum
          autoScrub = {
            enable = true;
            interval = "monthly";
          };
          trim.enable = true;
        };

        # Snapshots: only for data that cannot be recreated; none for /nix and scratch
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

                # 2. The four datasets are mounted, compressed, without access-time updates
                for path, name in [("/", "rpool/root"), ("/nix", "rpool/nix"), ("/home", "rpool/home"), ("/home/tester/scratch", "rpool/scratch")]:
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

                # 5. Scratch and /nix have no snapshots; scratch is limited and belongs to its user
                machine.fail("zfs list -H -t snapshot -o name | grep -qE '^rpool/(scratch|nix)@'")
                machine.succeed("test \"$(zfs get -H -o value quota rpool/scratch)\" = 1T")
                machine.succeed("su tester -c 'echo data > /home/tester/scratch/output'")

                # 6. The cache is capped at 8 GiB; scrub and TRIM are scheduled
                machine.succeed("test \"$(cat /sys/module/zfs/parameters/zfs_arc_max)\" = 8589934592")
                machine.succeed("systemctl is-enabled zfs-scrub.timer zpool-trim.timer")
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
