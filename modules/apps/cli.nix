# Terminal editor, network, disk and system tools; users opt in by importing homeManager.cli
{
  flake.modules.homeManager.cli =
    { pkgs, ... }:
    {
      # Sets EDITOR through Home Manager's session variables, loaded by the extraInit in modules/flake/host-machines.nix
      programs.vim = {
        enable = true;
        defaultEditor = true;
      };
      programs.btop.enable = true;

      home.packages = with pkgs; [
        tree
        nmap
        testdisk
        smartmontools
        fastfetch
      ];
    };
}
