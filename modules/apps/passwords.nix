# Bitwarden desktop and command-line clients; users opt in by importing homeManager.passwords
{
  flake.modules.homeManager.passwords =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        bitwarden-desktop
        bitwarden-cli
      ];
    };
}
