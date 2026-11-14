# Package set and overlays
#
# What it is    The pinned package set, narrow proprietary-package allowlist and two package overrides
# Who uses it   Every per-system package, check, shell and NixOS host built by this flake
# A maintainer adds An unfree package to both allowlists and docs/APPS.md, or a reviewed overlay here
# Protected     Yes: the package set changes every program and can add executable code (docs/UPKEEP.md)
{ inputs, ... }:
{
  perSystem =
    { system, ... }:
    {
      ## Part 1. Shared package set
      _module.args.pkgs = import inputs.nixpkgs {
        inherit system;
        config = {
          # Limit proprietary software to the reviewed applications and hardware drivers below
          # Additions also belong in checks.nix and docs/APPS.md
          allowUnfreePredicate =
            pkg:
            builtins.elem (inputs.nixpkgs.lib.getName pkg) [
              "obsidian"
              "discord"
              "spotify"
              "zoom"
              # Allow the proprietary graphics and dock drivers required by the laptop hardware
              "nvidia-x11"
              "nvidia-settings"
              "displaylink"
            ];
        };
        ## Part 2. Reviewed package overrides
        overlays = [
          # Take current pi from its separate unstable pin because NixOS 26.05 still carries an old release
          # Disable pi's feature that treats a value beginning with "!" as a command for obtaining a key
          # Its shared writable login file would otherwise let one session make another session run a command
          # Fail the build if the patch no longer reaches both copies; pi-login-commands checks the behaviour
          (_final: _prev: {
            pi-coding-agent = inputs.nixpkgs-pi.legacyPackages.${system}.pi-coding-agent.overrideAttrs (old: {
              postInstall = (old.postInstall or "") + ''
                patched=0
                while IFS= read -r file; do
                  sed -i -E 's/function executeCommandUncached\(commandConfig\) ?\{/&return void 0;/' "$file"
                  patched=$((patched + 1))
                done < <(grep -rlE 'function executeCommandUncached\(commandConfig\) ?\{' "$out/lib/node_modules" --include='*.js')
                # The program itself (the bundle) and the library that extensions import
                [ "$patched" = 2 ] || { echo "expected pi's command function in 2 files, found it in $patched"; exit 1; }
              '';
            });
          })
          # Take SearXNG from its own unstable pin because almost no default engines work in the 26.05 version
          (_final: _prev: {
            inherit (inputs.nixpkgs-search.legacyPackages.${system}) searxng;
          })
        ];
      };
    };
}
