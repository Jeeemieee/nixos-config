# Nix formatter
#
# What it is    The formatter used by nix fmt for files in this repository
# Who uses it   Maintainers and agents before they hand over a change
# A maintainer adds Nothing; formatting is deliberately separate from nix flake check
# Protected     Yes: this decides which program nix fmt executes (docs/UPKEEP.md)
{
  perSystem =
    { pkgs, ... }:
    {
      # Format the repository's Nix tree with nixfmt without making checks rewrite files
      formatter = pkgs.nixfmt-tree;
    };
}
