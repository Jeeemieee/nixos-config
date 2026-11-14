# System-wide direnv with nix-direnv; the only place direnv is hooked into shells. Hosts opt in by importing nixos.direnv
# direnv runs in the user's own shell, outside every pi sandbox, so nothing that an agent can write may be evaluated by it:
#   - nix-direnv's cache of a project's dev shell is kept in the user's cache folder, which no sandbox sees, not in the project
#   - a changed flake is only evaluated when the user asks for it with `nix-direnv-reload`
{
  flake.modules.nixos.direnv =
    { pkgs, ... }:
    {
      programs.direnv = {
        enable = true;
        # Already the default, stated to record that devShells are cached and GC-rooted
        nix-direnv.enable = true;
        direnvrcExtra = ''
          # One folder per project in ~/.cache/direnv/layouts, named by a digest of the project's path and the path itself
          direnv_layout_dir() {
            echo "$HOME/.cache/direnv/layouts/$(${pkgs.coreutils}/bin/sha256sum <<< "$PWD" | ${pkgs.coreutils}/bin/cut -c1-16)''${PWD//[^a-zA-Z0-9]/-}"
          }
          # Without this, nix-direnv evaluates a changed flake by itself at the next prompt, with the flake's shell hook
          nix_direnv_manual_reload
        '';
      };
    };
}
