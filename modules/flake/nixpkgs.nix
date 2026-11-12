{ inputs, ... }:
{
  perSystem =
    { system, ... }:
    {
      _module.args.pkgs = import inputs.nixpkgs {
        inherit system;
        config = {
          # Unfree software is limited to this allowlist
          # Every new unfree package needs an explicit entry here and in unfreeAllowed in modules/flake/checks.nix, plus a row in docs/APPS.md
          allowUnfreePredicate =
            pkg:
            builtins.elem (inputs.nixpkgs.lib.getName pkg) [
              "obsidian"
              "discord"
              "spotify"
              "zoom"
            ];
        };
        overlays = [
          # pi from nixos-unstable: 26.05 ships 0.75.4, while the user works with the current 1.x
          (_final: _prev: {
            inherit (inputs.nixpkgs-unstable.legacyPackages.${system}) pi-coding-agent;
          })
        ];
      };
    };
}
