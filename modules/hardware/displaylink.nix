# DisplayLink dock graphics
#
# What it is    The USB display driver and ordinary modesetting fallback used by DisplayLink docks
# Who uses it   A NixOS host by importing nixos.displaylink
# A host adds   The driver file once per version by following the missing-file build message
# Protected     No: the explicit proprietary download only adds display drivers (docs/MIMIR.md)
{
  flake.modules.nixos.displaylink = {
    # Load the DisplayLink manager and EVDI module while retaining normal graphics modesetting
    services.xserver.videoDrivers = [
      "displaylink"
      "modesetting"
    ];
  };
}
