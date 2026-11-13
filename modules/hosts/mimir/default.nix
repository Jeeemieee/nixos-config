# The laptop: Dell Precision 7680 (Intel i7-13850HX, NVIDIA RTX 3500 Ada)
{ config, ... }:
let
  inherit (config.flake) modules;
in
{
  flake.modules.nixos.host-mimir = {
    imports = [
      modules.nixos.workstation
      modules.nixos.login-password
      modules.nixos.disk
      modules.nixos.boot
      modules.nixos.secure-boot
      modules.nixos.laptop
      modules.nixos.nvidia-offload
      modules.nixos.displaylink
      modules.nixos.backup
    ];

    # The laptop's own age recipient is enrolled in nixos-secrets when it is installed
    hostSpec.hasSecrets = true;

    networking.hostName = "mimir";
    # Required by ZFS, which refuses to import a pool last used by another host ID
    networking.hostId = "30d630f0";

    # hostSpec.disk.device is set by the installer (modules/install), for the disk that was confirmed by its serial number
    hostSpec.disk = {
      scratchUser = "jeeemieee";
      # For the 2 TB disk: 1863 GiB, of which about 1770 GiB is usable after the boot partition, swap and ZFS's own reserve
      # If every limit were reached while /home is at its reservation, about 120 GiB would be left
      # Each can be changed on the running system with `sudo zfs set <property>=<size> rpool/<dataset>`
      homeReservation = "600G";
      nixQuota = "250G";
      scratchQuota = "600G";
      workersQuota = "200G";
    };

    hardware.cpu.intel.updateMicrocode = true;
    # Intel's thermal daemon, as on the Ubuntu install
    services.thermald.enable = true;
    # The 3Dconnexion SpaceMouse, through the free driver that Blender uses
    hardware.spacenavd.enable = true;
    # The system disk sits in a USB enclosure for now; without these the first boot stage does not find it there
    boot.initrd.availableKernelModules = [
      "usb_storage"
      "uas"
    ];
    boot.kernelModules = [ "kvm-intel" ];

    # From lspci: 00:02.0 Intel graphics, 01:00.0 NVIDIA
    hardware.nvidia.prime = {
      intelBusId = "PCI:0:2:0";
      nvidiaBusId = "PCI:1:0:0";
    };

    home-manager.users.jeeemieee.home.stateVersion = "26.05";
    system.stateVersion = "26.05";
  };
}
