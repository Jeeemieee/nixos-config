# Engineering applications
#
# What it is    Tools for visualisation, plotting, mesh work, 3D printing and STL viewing
# Who uses it   A Home Manager user by importing homeManager.engineering; the workstation account imports it
# A user adds   Nothing; the module installs the related applications together
# Protected     No: these are ordinary user applications
{
  flake.modules.homeManager.engineering =
    { pkgs, ... }:
    {
      ## Part 1. Applications
      # Cover the routine viewing, plotting, mesh and slicing workflows
      home.packages = with pkgs; [
        paraview
        prusa-slicer
        fstl
        meshlab
        gnuplot
      ];

      ## Part 2. STL viewer menu entry
      # Add the menu entry that nixpkgs' fstl package omits, following upstream's desktop file
      xdg.desktopEntries.fstl = {
        name = "fstl";
        genericName = "Fast STL Viewer";
        exec = "fstl %U";
        icon = "${pkgs.fstl.src}/xdg/icons/fstlapp-fstl_256x256.png";
        mimeType = [ "model/stl" ];
        categories = [ "Utility" ];
      };
    };
}
