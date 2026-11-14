# Media applications
#
# What it is    Desktop programs for chat, music, video playback and media conversion
# Who uses it   A Home Manager user by importing homeManager.media; the workstation account imports it
# A user adds   Nothing; the module installs the related applications together
# Protected     No: these are ordinary user applications
{
  flake.modules.homeManager.media =
    { pkgs, ... }:
    {
      # Keep communication, streaming, playback and conversion tools in one group
      home.packages = with pkgs; [
        # These two proprietary packages are explicitly allowed in modules/flake/nixpkgs.nix
        discord
        spotify

        vlc
        ffmpeg
      ];
    };
}
