# NVIDIA graphics next to an integrated GPU, used on demand; hosts opt in by importing nixos.nvidia-offload
# and set hardware.nvidia.prime.intelBusId and nvidiaBusId (from lspci)
{
  flake.modules.nixos.nvidia-offload = {
    # Loads the NVIDIA driver, also on Wayland; it provides CUDA in /run/opengl-driver/lib
    services.xserver.videoDrivers = [ "nvidia" ];

    hardware.nvidia = {
      # The open kernel modules, which NVIDIA recommends from the RTX 20 series on; the user-space driver stays unfree
      open = true;

      # The integrated GPU drives the desktop; a program uses the NVIDIA GPU when asked (nvidia-offload <program>) or through CUDA
      prime.offload = {
        enable = true;
        enableOffloadCmd = true;
      };

      powerManagement = {
        # Saves and restores the GPU's state around suspend
        enable = true;
        # Powers the GPU down while nothing uses it
        finegrained = true;
      };
    };

    # Containers can use the GPU: the toolkit describes it as a device, and rootless Docker is told to accept such descriptions
    # A container asks for it with `--device nvidia.com/gpu=all`
    hardware.nvidia-container-toolkit.enable = true;
    virtualisation.docker.rootless.daemon.settings.features.cdi = true;
  };
}
