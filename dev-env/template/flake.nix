{
  description = "Project development environment";

  # Building blocks, defined once for all projects; update them with: nix flake update blocks
  inputs.blocks.url = "github:Jeeemieee/nixos-config";

  outputs =
    { self, blocks }:
    {
      # Blocks: "python", "cpp", and at most one of "numerics-cpu", "numerics-cuda"
      devShells.x86_64-linux.default = blocks.lib.devShell {
        blocks = [
          "python"
          "numerics-cpu"
        ];
        packages = pkgs: [ ];
      };
    };
}
