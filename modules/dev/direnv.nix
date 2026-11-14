# Safe automatic development shells
#
# What it is    The one system-wide direnv hook, using nix-direnv with manual reloads and an external cache
# Who uses it   A NixOS host by importing nixos.direnv; the workstation profile imports it
# A host adds   An .envrc in each project that should enter its development shell
# Protected     Yes: direnv runs in the user's own shell outside every pi sandbox (docs/UPKEEP.md)
{
  flake.modules.nixos.direnv =
    { pkgs, ... }:
    {
      programs.direnv = {
        # Provide the only shell hook allowed to start project environments automatically
        enable = true;

        # Record explicitly that development shells are cached and kept as garbage-collection roots
        nix-direnv.enable = true;
        # Keep generated environments outside project folders and reload changed flakes only on request
        direnvrcExtra = ''
          # One cache folder per project, named from a digest and a readable form of its path
          direnv_layout_dir() {
            echo "$HOME/.cache/direnv/layouts/$(${pkgs.coreutils}/bin/sha256sum <<< "$PWD" | ${pkgs.coreutils}/bin/cut -c1-16)''${PWD//[^a-zA-Z0-9]/-}"
          }
          # Prevent a changed flake and its shell hook from running automatically at the next prompt
          nix_direnv_manual_reload
        '';
      };
    };
}
