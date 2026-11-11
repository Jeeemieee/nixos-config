{ inputs, ... }:
{
  imports = [
    inputs.treefmt-nix.flakeModule
  ];

  perSystem =
    { ... }:
    {
      treefmt.config = {
        projectRootFile = "flake.nix";
        # `nix fmt` formats with nixfmt; nix flake check does not enforce it
        flakeCheck = false;
        programs = {
          nixfmt.enable = true;
        };
      };
    };
}
