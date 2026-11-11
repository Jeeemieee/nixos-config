# Visualisation, slicing and STL viewing; users opt in by importing homeManager.engineering
{
  flake.modules.homeManager.engineering =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        paraview
        prusa-slicer
        fstl
      ];

      # nixpkgs' fstl installs no menu entry; this mirrors upstream's xdg/fstlapp-fstl.desktop
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
