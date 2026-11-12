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
    ];

    # The laptop's own age recipient is enrolled in nixos-secrets when it is installed
    hostSpec.hasSecrets = true;

    networking.hostName = "mimir";
    # Required by ZFS, which refuses to import a pool last used by another host ID
    networking.hostId = "30d630f0";

    # hostSpec.disk.device is set when the laptop is installed: the disk is named by model and serial number, never guessed
    hostSpec.disk.scratchUser = "jeeemieee";

    hardware.cpu.intel.updateMicrocode = true;
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
