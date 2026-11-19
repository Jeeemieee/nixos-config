{
  description = "Project development environment";

  # Building blocks, defined once for all projects; update them with: nix flake update blocks
  # This folder holds only flake.nix and flake.lock: it is copied into the Nix store whenever the shell is entered
  inputs.blocks.url = "github:Jeeemieee/nixos-config?dir=dev-env";

  outputs =
    { self, blocks }:
    {
      # Blocks: "python", "cpp", "openfoam", and at most one of "numerics-cpu", "numerics-cuda"
      devShells.x86_64-linux.default = blocks.lib.devShell {
        blocks = [
          "python"
          "numerics-cpu"
        ];
        packages = pkgs: [ ];
      };
    };
}
