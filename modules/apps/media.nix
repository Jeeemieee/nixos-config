# Chat, music and video; users opt in by importing homeManager.media
{
  flake.modules.homeManager.media =
    { pkgs, ... }:
    {
      home.packages = with pkgs; [
        # Both unfree, allowed in modules/flake/nixpkgs.nix
        discord
        spotify

        vlc
        ffmpeg
      ];
    };
}
