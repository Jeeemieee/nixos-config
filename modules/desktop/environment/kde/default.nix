# KDE Plasma desktop
#
# What it is    Plasma 6, its SDDM login screen and the shared desktop services
# Who uses it   A NixOS host by importing nixos.desktop-kde; the workstation profile imports it
# A host adds   A matching Home Manager desktop-kde module for the user's Plasma settings
# Protected     No: the desktop can be replaced without changing accounts, boot or recovery safeguards
{ config, ... }:
{
  flake.modules.nixos.desktop-kde = {
    # Include the audio and other shared services needed by a graphical desktop
    imports = [ config.flake.modules.nixos.desktop ];

    # Show Plasma's supported graphical login screen
    services.displayManager.sddm.enable = true;

    # Install and start Plasma 6 as the desktop session
    services.desktopManager.plasma6.enable = true;

    # Run Electron and Chromium applications natively on Wayland instead of through XWayland
    environment.sessionVariables.NIXOS_OZONE_WL = "1";

    # GTK and Firefox-based programs ask the desktop for its file dialog, so that they show Plasma's, with its path bar and places
    # A program that builds its own dialog (GIMP, Blender) keeps it
    environment.sessionVariables.GTK_USE_PORTAL = "1";
  };
}
