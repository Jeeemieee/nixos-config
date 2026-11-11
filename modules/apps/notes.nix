# Notes and reference management, packages only; users opt in by importing homeManager.notes
{
  flake.modules.homeManager.notes =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        # Unfree, allowed in modules/flake/nixpkgs.nix
        obsidian
        zotero
      ];
    };
}
