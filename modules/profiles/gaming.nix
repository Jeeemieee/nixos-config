# Gaming desktop profile
#
# What it is    Steam and launcher integration, AMD graphics, diagnostics and save export
# Who uses it   Odin only, beside the shared workstation profile
# A host adds   No account or game library; those remain machine state
# Protected     Yes: this adds proprietary software and a privileged reboot action
{ config, ... }:
let
  inherit (config.flake) modules;
in
{
  ## Part 1. System gaming support
  flake.modules.nixos.gaming =
    { pkgs, ... }:
    {
      # Steam supplies Valve Proton; Proton-GE remains an explicit per-game alternative
      programs.steam = {
        enable = true;
        extraCompatPackages = [ pkgs.proton-ge-bin ];
      };
      programs.gamescope.enable = true;
      programs.gamemode.enable = true;

      # Give controllers and Valve devices their reviewed udev rules without opening remote-play ports
      hardware.steam-hardware.enable = true;

      # Use the kernel's amdgpu driver and Mesa RADV for native and 32-bit games
      services.xserver.videoDrivers = [ "amdgpu" ];
      hardware.graphics = {
        enable = true;
        enable32Bit = true;
      };
      hardware.enableRedistributableFirmware = true;

      # Keep launchers, overlays, save export and the Windows action in the user's profile
      home-manager.users.jeeemieee.imports = [ modules.homeManager.gaming ];
    };

  ## Part 2. User applications and save export
  flake.modules.homeManager.gaming =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      # The existing /home backup includes this folder; game libraries remain outside it
      savePath = "${config.home.homeDirectory}/game-saves/ludusavi";
    in
    {
      home.packages = with pkgs; [
        heroic
        lutris
        ludusavi
      ];

      # Install the overlay and its configuration support without forcing it onto every program
      programs.mangohud.enable = true;

      # systemctl asks polkit to authenticate the user before scheduling the one-shot boot entry
      xdg.desktopEntries.reboot-windows = {
        name = "Reboot into Windows";
        genericName = "Restart once into Windows";
        exec = "systemctl reboot --boot-loader-entry=auto-windows";
        icon = "system-reboot";
        terminal = false;
        categories = [ "System" ];
      };

      # Export non-cloud saves every day into /home so restic protects them with personal data
      systemd.user.services.ludusavi-backup = {
        Unit = {
          Description = "Export game saves with Ludusavi";
          After = [ "graphical-session.target" ];
        };
        Service = {
          Type = "oneshot";
          ExecStart = "${pkgs.ludusavi}/bin/ludusavi backup --force --no-cloud-sync --path ${lib.escapeShellArg savePath}";
        };
      };
      systemd.user.timers.ludusavi-backup = {
        Unit.Description = "Daily Ludusavi save export";
        Timer = {
          OnCalendar = "daily";
          Persistent = true;
          RandomizedDelaySec = "30m";
          Unit = "ludusavi-backup.service";
        };
        Install.WantedBy = [ "timers.target" ];
      };
    };
}
