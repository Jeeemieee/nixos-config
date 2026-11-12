# DisplayLink docks (USB graphics); hosts opt in by importing nixos.displaylink
# The driver is unfree and cannot be downloaded by Nix: fetch it once per driver version, which accepts DisplayLink's licence
# (the build prints the command when the file is missing), see docs/MIMIR.md
{
  flake.modules.nixos.displaylink = {
    # Adds the evdi kernel module and the DisplayLink manager service
    services.xserver.videoDrivers = [
      "displaylink"
      "modesetting"
    ];
  };
}
