# Meeting and remote-desktop applications
#
# What it is    Clients for Teams, Zoom and RustDesk
# Who uses it   A Home Manager user by importing homeManager.meetings; the workstation account imports it
# A user adds   Nothing; the module installs and adjusts the clients together
# Protected     No: these are ordinary user applications
{
  flake.modules.homeManager.meetings =
    { pkgs, ... }:
    {
      ## Part 1. Notification behaviour
      # Stop Teams flashing its task-bar entry for every notification
      xdg.configFile."teams-for-linux/config.json".text = builtins.toJSON {
        disableNotificationWindowFlash = true;
      };

      ## Part 2. Applications
      # Install the meeting and remote-support clients used on the workstation
      home.packages = with pkgs; [
        # Unofficial Teams client around Teams for the web; Microsoft has no native Linux client
        teams-for-linux
        # This proprietary package is explicitly allowed in modules/flake/nixpkgs.nix
        zoom-us
        # Use RustDesk's Flutter client because the plain package uses the legacy unfree interface
        rustdesk-flutter
      ];
    };
}
