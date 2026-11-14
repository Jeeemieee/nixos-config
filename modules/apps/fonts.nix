# Office-compatible fonts
#
# What it is    Free fonts with the same character sizes as common Microsoft Office fonts
# Who uses it   A NixOS host by importing nixos.fonts; the workstation profile imports it
# A host adds   Nothing; fontconfig supplies the familiar font-name aliases
# Protected     No: fonts do not control access, data recovery or system safeguards
{
  flake.modules.nixos.fonts =
    { pkgs, ... }:
    {
      # Keep Office documents laid out correctly through fontconfig's metric-compatible aliases
      # Calibri maps to Carlito, Cambria to Caladea, and the older Microsoft fonts to Liberation
      fonts.packages = with pkgs; [
        carlito
        caladea
        liberation_ttf
      ];
    };
}
