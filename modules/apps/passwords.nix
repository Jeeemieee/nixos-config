# Password manager
#
# What it is    Bitwarden's desktop and command-line clients, with the desktop app started at login
# Who uses it   A Home Manager user by importing homeManager.passwords; the workstation account imports it
# A user adds   A vault and, for GitHub, the SSH key used by modules/dev/git/github.nix
# Protected     No: the module installs the client but stores no vault data or key
{
  flake.modules.homeManager.passwords =
    { pkgs, ... }:
    {
      ## Part 1. Applications
      # Provide both the graphical client and the command used in a terminal
      home.packages = with pkgs; [
        bitwarden-desktop
        bitwarden-cli
      ];

      ## Part 2. Login start
      # Start Bitwarden with the desktop because its SSH agent only exists while the app runs
      # Replace Bitwarden's own autostart file so it cannot block a later Home Manager activation
      # Point at the installed package again after every rebuild
      xdg.configFile."autostart/bitwarden.desktop" = {
        force = true;
        text = ''
          [Desktop Entry]
          Type=Application
          Name=Bitwarden
          Exec=${pkgs.bitwarden-desktop}/bin/bitwarden --autostart
          Icon=bitwarden
          StartupNotify=false
          Terminal=false
        '';
      };
    };
}
