{ config, ... }:
{
  # Reusable desktop selection for the VM and, later, physical workstations
  flake.modules.nixos.desktop-kde = {
    imports = [ config.flake.modules.nixos.desktop ];

    services.displayManager.sddm.enable = true;
    services.desktopManager.plasma6.enable = true;

    # Electron and Chromium apps from nixpkgs run natively on Wayland instead of through XWayland
    environment.sessionVariables.NIXOS_OZONE_WL = "1";
  };
}
