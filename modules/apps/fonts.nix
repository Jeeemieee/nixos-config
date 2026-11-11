# Metric-compatible fonts for Microsoft Office documents; hosts opt in by importing nixos.fonts
{
  flake.modules.nixos.fonts =
    { pkgs, ... }:
    {
      # fontconfig's metric aliases map Calibri to Carlito, Cambria to Caladea, and Arial, Times New Roman and Courier New to Liberation
      fonts.packages = with pkgs; [
        carlito
        caladea
        liberation_ttf
      ];
    };
}
