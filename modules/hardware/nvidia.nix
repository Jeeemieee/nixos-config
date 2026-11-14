# On-demand NVIDIA graphics
#
# What it is    PRIME offload, suspend handling and container access for NVIDIA beside an integrated GPU
# Who uses it   A NixOS host by importing nixos.nvidia-offload
# A host adds   The integrated and NVIDIA PCI bus identifiers reported by lspci
# Protected     No: the module enables graphics hardware but does not control boot, disks or accounts
{
  flake.modules.nixos.nvidia-offload = {
    # Load the NVIDIA driver on Wayland and expose its CUDA libraries through the system graphics path
    services.xserver.videoDrivers = [ "nvidia" ];

    hardware.nvidia = {
      # Use NVIDIA's recommended open kernel module while retaining its proprietary user-space driver
      open = true;

      # Let the integrated GPU drive the desktop and use NVIDIA only through nvidia-offload or CUDA
      prime.offload = {
        enable = true;
        enableOffloadCmd = true;
      };

      powerManagement = {
        # Save and restore GPU state across suspend
        enable = true;
        # Power the GPU down while no program uses it
        finegrained = true;
      };
    };

    # Describe the GPU as a CDI device and let rootless Docker accept that description
    # A container requests it with --device nvidia.com/gpu=all
    hardware.nvidia-container-toolkit.enable = true;
    virtualisation.docker.rootless.daemon.settings.features.cdi = true;
  };
}
