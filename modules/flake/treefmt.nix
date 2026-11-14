# `nix fmt` formats every Nix file with nixfmt; nix flake check does not enforce it
{
  perSystem =
    { pkgs, ... }:
    {
      formatter = pkgs.nixfmt-tree;
    };
}
