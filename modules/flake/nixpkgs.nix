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
              # Laptop hardware: the NVIDIA user-space driver with its settings program, and the DisplayLink dock driver
              "nvidia-x11"
              "nvidia-settings"
              "displaylink"
            ];
        };
        overlays = [
          # pi from its own nixos-unstable pin: 26.05 ships 0.75.4, while the user works with the current 1.x
          (_final: _prev: {
            inherit (inputs.nixpkgs-pi.legacyPackages.${system}) pi-coding-agent;
          })
          # SearXNG from its own nixos-unstable pin: with the version of 26.05 only one of the default search engines still answered
          (_final: _prev: {
            inherit (inputs.nixpkgs-search.legacyPackages.${system}) searxng;
          })
        ];
      };
    };
}
