# Chat and music; users opt in by importing homeManager.media
{
  flake.modules.homeManager.media =
    { pkgs, ... }:
    {
      # Both unfree, allowed in modules/flake/nixpkgs.nix
      home.packages = with pkgs; [
        discord
        spotify
      ];
    };
}
