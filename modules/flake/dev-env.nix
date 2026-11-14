# Project development environments
#
# What it is    The reusable development-shell library, project template and checks from dev-env/
# Who uses it   Project flakes through flake.lib.devShell or the project template
# A project adds Its chosen blocks and any extra packages described in docs/DEV-ENVIRONMENTS.md
# Protected     Yes: the library can run shell hooks in the user's own project shell (docs/UPKEEP.md)
{ inputs, lib, ... }:
let
  # Build project shells from the separate development pin
  # This keeps them independent of the hosts and their unfree allowlist
  devShell = import ../../dev-env/dev-shell.nix {
    nixpkgs = inputs.nixpkgs-unstable;
    system = "x86_64-linux";
  };
in
{
  ## Part 1. Public library and template
  # Let projects compose named blocks, for example Python with the CUDA numerical stack
  flake.lib.devShell = devShell;

  # Offer a ready project flake through nix flake init -t github:Jeeemieee/nixos-config#project
  flake.templates.project = {
    path = ../../dev-env/template;
    description = "Project with a development environment from building blocks";
  };

  ## Part 2. Development-environment checks
  perSystem =
    { system, ... }:
    {
      # Test the supported blocks, combinations, one-PETSc rule and explicit refusals in the Nix sandbox
      # For OpenFOAM: serial, parallel, with wmake, beside PETSc, and where it keeps the user's own solvers
      checks = lib.mapAttrs' (name: lib.nameValuePair "dev-env-${name}") (
        import ../../dev-env/checks.nix {
          nixpkgs = inputs.nixpkgs-unstable;
          inherit system devShell;
        }
      );
    };
}
