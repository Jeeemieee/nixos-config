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
          # pi takes a value that starts with "!" in its files as a command to run for a key. The login file is shared by all pi
          # sessions and each can write it, so one session could make every other run a command: here pi never runs such a command
          # The build fails when a new version has no such function in both places; the pi-login-commands check tests the behaviour
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
          # SearXNG from its own nixos-unstable pin: with the version of 26.05 only one of the default search engines still answered
          (_final: _prev: {
            inherit (inputs.nixpkgs-search.legacyPackages.${system}) searxng;
          })
        ];
      };
    };
}
