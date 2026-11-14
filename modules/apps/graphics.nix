# Graphics applications
#
# What it is    Tools for raster, vector and 3D work, image viewing and format conversion
# Who uses it   A Home Manager user by importing homeManager.graphics; the workstation account imports it
# A user adds   Nothing; the module installs the related applications together
# Protected     No: these are ordinary user applications
{
  flake.modules.homeManager.graphics =
    { pkgs, ... }:
    {
      # Cover image editing, drawing, modelling, viewing and command-line conversion
      home.packages = with pkgs; [
        gimp
        inkscape
        blender
        gthumb
        imagemagick
      ];
    };
}
