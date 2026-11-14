# Development-environment building blocks for projects; see docs/DEV-ENVIRONMENTS.md
# The blocks are plain Nix in dev-env/, outside modules/, where every file would be loaded as a flake-parts module
{ inputs, lib, ... }:
let
  # Built from nixpkgs-unstable (PETSc 3.25), independent of the hosts' package set and its unfree allowlist
  devShell = import ../../dev-env/dev-shell.nix {
    nixpkgs = inputs.nixpkgs-unstable;
    system = "x86_64-linux";
  };
in
{
  # blocks.lib.devShell { blocks = [ "python" "numerics-cuda" ]; packages = pkgs: [ ]; }
  flake.lib.devShell = devShell;

  # nix flake init -t github:Jeeemieee/nixos-config#project
  flake.templates.project = {
    path = ../../dev-env/template;
    description = "Project with a development environment from building blocks";
  };

  perSystem =
    { system, ... }:
    {
      # Each block and combination in the Nix sandbox: MPI, PETSc with MUMPS from Python and C, SLEPc, Fortran, one PETSc per shell, the refusals;
      # OpenFOAM serial, parallel, with wmake, beside PETSc, and where it keeps the user's own solvers
      checks = lib.mapAttrs' (name: lib.nameValuePair "dev-env-${name}") (
        import ../../dev-env/checks.nix {
          nixpkgs = inputs.nixpkgs-unstable;
          inherit system devShell;
        }
      );
    };
}
