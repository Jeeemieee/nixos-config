# System-wide direnv with nix-direnv; the only place direnv is hooked into shells
{
  flake.modules.nixos.direnv = {
    programs.direnv = {
      enable = true;
      # Already the default, stated to record that devShells are cached and GC-rooted
      nix-direnv.enable = true;
    };
  };
}
