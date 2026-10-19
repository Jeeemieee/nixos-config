{ config, ... }:
{
  # Reusable desktop selection for the VM and, later, physical workstations
  flake.modules.nixos.desktop-kde = {
    imports = [ config.flake.modules.nixos.desktop ];

    services.displayManager.sddm.enable = true;
    services.desktopManager.plasma6.enable = true;
  };
}
