# Raster, vector and 3D graphics, image viewing and conversion; users opt in by importing homeManager.graphics
{
  flake.modules.homeManager.graphics =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        gimp
        inkscape
        blender
        gthumb
        imagemagick
      ];
    };
}
