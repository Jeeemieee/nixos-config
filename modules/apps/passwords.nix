# Bitwarden desktop and command-line clients; users opt in by importing homeManager.passwords
# The desktop app also holds the SSH key for GitHub and hands it to git while the vault is unlocked (modules/dev/git/github.nix)
{
  flake.modules.homeManager.passwords =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        bitwarden-desktop
        bitwarden-cli
      ];

      # The app starts with the desktop session, in the task bar: its SSH agent only exists while it runs
      # Bitwarden writes a file of this name itself when its own "Start automatically on login" is on; without force, that file would
      # stop every later Home Manager activation ("would be clobbered"). The declared one points at the installed version after every rebuild
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
