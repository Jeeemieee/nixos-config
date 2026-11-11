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
      };
    };
}
