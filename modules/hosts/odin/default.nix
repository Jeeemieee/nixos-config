# The gaming desktop: hardware-independent configuration
{ config, ... }:
let
  inherit (config.flake) modules;
in
{
  ## Part 1. Facts that the user supplies after inspecting the real machine
  flake.modules.nixos.odin-facts =
    { lib, ... }:
    {
      options.hostSpec.odin = {
        systemDiskById = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          example = "/dev/disk/by-id/nvme-Example_1TB_SERIAL";
          description = "Stable by-id path of Odin's system disk. The installer refuses while it is null.";
        };
        hostId = lib.mkOption {
          type = lib.types.nullOr (lib.types.strMatching "[0-9a-fA-F]{8}");
          default = null;
          example = "8425e349";
          description = "Eight hexadecimal digits used as Odin's ZFS host ID. The installer refuses while it is null.";
        };
        networkDevices = lib.mkOption {
          type = lib.types.listOf lib.types.nonEmptyStr;
          default = [ ];
          example = [
            "enp5s0"
            "wlp6s0"
          ];
          description = "Names of Odin's physical network devices. The installer refuses while the list is empty.";
        };
      };
    };

  ## Part 2. Production host composition
  flake.modules.nixos.host-odin =
    { config, lib, ... }:
    let
      facts = config.hostSpec.odin;
    in
    {
      imports = [
        modules.nixos.odin-facts
        modules.nixos.workstation
        modules.nixos.gaming
        modules.nixos.login-password
        modules.nixos.disk
        modules.nixos.boot
        modules.nixos.secure-boot
        modules.nixos.backup
        modules.nixos.tailscale-ssh-server
      ];

      networking.hostName = "odin";
      # The checks need an evaluable system before the real value is known; the installer refuses this sentinel
      networking.hostId = if facts.hostId == null then "00000000" else facts.hostId;

      hardware.cpu.intel.updateMicrocode = true;
      boot.kernelModules = [ "kvm-intel" ];

      # Keep downloaded game payloads out of /home's backup while preserving launcher settings and save exports
      services.restic.backups.home.exclude = lib.mkAfter [
        "/home/*/.local/share/Steam/steamapps"
        "/home/*/.steam/steam/steamapps"
        "/home/*/Games"
      ];

      hostSpec.disk = {
        # Disko needs a value during evaluation; only the installer may replace it after its fact preflight
        device =
          if facts.systemDiskById == null then
            "/dev/disk/by-id/ODIN-SYSTEM-DISK-NOT-SET"
          else
            facts.systemDiskById;
        efiSizeMiB = 2048;
        dualBoot.enable = true;
        scratchUser = "jeeemieee";

        # The 1 TB plan keeps 50 GiB outside the declared maxima after Windows, EFI and swap
        homeReservation = "200G";
        nixQuota = "150G";
        scratchQuota = "275G";
        # Keep the shared dataset recipe without importing or running the worker subsystem
        workersQuota = "1G";
      };

      home-manager.users.jeeemieee.home.stateVersion = "26.05";
      system.stateVersion = "26.05";
    };
}
