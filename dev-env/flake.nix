# The building blocks as a flake of their own
#
# What it is    The development-shell library and the project template, with nixpkgs as their only input
# Who uses it   Project flakes: inputs.blocks.url = "github:Jeeemieee/nixos-config?dir=dev-env"; and this repository,
#               whose nixpkgs-unstable follows this flake's nixpkgs (flake.nix), so the checks test what projects get
# A project adds Its chosen blocks and any extra packages described in docs/DEV-ENVIRONMENTS.md
# Protected     Yes: the library can run shell hooks in the user's own project shell (docs/UPKEEP.md)
{
  description = "Development-environment building blocks: Python, C++, PETSc, CUDA, OpenFOAM";

  # The one pin of the blocks; move it with: config update dev
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    {
      # A project's shell from named blocks, for example Python with the CPU numerical stack
      lib.devShell = import ./dev-shell.nix {
        inherit nixpkgs;
        system = "x86_64-linux";
      };
      # The blocks' package set, for a project that builds a package of its own with the shell's Python
      lib.pkgs = nixpkgs.legacyPackages.x86_64-linux;

      # A ready project: nix flake init -t "github:Jeeemieee/nixos-config?dir=dev-env#project"
      templates.project = {
        path = ./template;
        description = "Project with a development environment from building blocks";
      };
    };
}
