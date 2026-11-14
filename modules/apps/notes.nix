# Notes and references
#
# What it is    Desktop applications for personal notes and academic references
# Who uses it   A Home Manager user by importing homeManager.notes; the workstation account imports it
# A user adds   Nothing here; application data remains in the user's home folder
# Protected     No: these are ordinary user applications
{
  flake.modules.homeManager.notes =
    { pkgs, ... }:
    {
      # Install both applications without declaring their private libraries or notes
      home.packages = with pkgs; [
        # This proprietary package is explicitly allowed in modules/flake/nixpkgs.nix
        obsidian
        zotero
      ];
    };
}
