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

      # Keeps shells and long runs alive when a terminal closes or an SSH connection drops; Ctrl+b d detaches, tmux attach returns
      programs.tmux = {
        enable = true;
        mouse = true;
        historyLimit = 50000;
      };

      home.packages = with pkgs; [
        tree
        nmap
        testdisk
        smartmontools
        fastfetch
        # Shows what takes space in a folder, such as ~/scratch; deletes only on request
        ncdu
      ];
    };
}
