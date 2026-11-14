# Command-line tools
#
# What it is    A terminal editor plus tools for sessions, networks, disks and system information
# Who uses it   A Home Manager user by importing homeManager.cli; the workstation account imports it
# A user adds   Nothing; the module supplies the programs and packages together
# Protected     No: these are user tools and do not define privileged services or safeguards
{
  flake.modules.homeManager.cli =
    { pkgs, ... }:
    {
      ## Part 1. Interactive terminal programs
      # Set EDITOR through the session variables loaded by modules/flake/host-machines.nix
      programs.vim = {
        enable = true;
        defaultEditor = true;
      };
      # Provide a readable interactive view of running processes and resource use
      programs.btop.enable = true;

      # Keep shells and long jobs alive when a terminal closes or an SSH connection drops
      # Ctrl+b d detaches from a session, and tmux attach returns to it
      programs.tmux = {
        enable = true;
        mouse = true;
        historyLimit = 50000;
      };

      ## Part 2. Small system tools
      # Cover routine directory, network, disk-recovery, disk-health and machine-inspection tasks
      home.packages = with pkgs; [
        tree
        nmap
        testdisk
        smartmontools
        fastfetch
        # Show what takes space in a folder and delete only when explicitly asked
        ncdu
      ];
    };
}
