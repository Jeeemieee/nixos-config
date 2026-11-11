# Raster, vector and 3D graphics; users opt in by importing homeManager.graphics
{
  flake.modules.homeManager.graphics =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        gimp
        inkscape
        blender
      ];
    };
}
