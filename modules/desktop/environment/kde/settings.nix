# Plasma user settings
#
# What it is    The Plasma choices reapplied at login while undeclared choices remain user-controlled
# Who uses it   A Home Manager user by importing homeManager.desktop-kde; the workstation account imports it
# A user adds   Nothing; private desktop names come separately from keyboard.nix
# Protected     No: these settings only control the user's desktop session
{ inputs, ... }:
{
  flake.modules.homeManager.desktop-kde =
    { lib, ... }:
    {
      # Use plasma-manager so Home Manager can maintain Plasma's settings
      imports = [ inputs.plasma-manager.homeModules.plasma-manager ];

      programs.plasma = {
        # Apply the declared choices whenever the Home Manager generation activates
        enable = true;

        ## Part 1. Appearance and keyboard
        # Use Plasma's dark Breeze theme throughout the desktop
        workspace.lookAndFeel = "org.kde.breezedark.desktop";

        # Make the numeric keypad enter numbers immediately after login
        input.keyboard.numlockOnStartup = "on";

        ## Part 2. Language and formats
        # Match Plasma's per-user locale to the system choices so it does not override them differently
        configFile.plasma-localerc = {
          Formats = {
            LANG = "en_GB.UTF-8";
            # Restore British dates on a machine that had previously saved Dutch dates
            LC_TIME = "en_GB.UTF-8";
          }
          // lib.genAttrs [
            "LC_NUMERIC"
            "LC_MONETARY"
            "LC_PAPER"
            "LC_NAME"
            "LC_ADDRESS"
            "LC_TELEPHONE"
            "LC_MEASUREMENT"
          ] (_: "nl_NL.UTF-8");
          # Keep Plasma's translated interface in British English
          Translations.LANGUAGE = "en_GB";
        };

        ## Part 3. Locking and screen edges
        # Use 9, Plasma's value for no edge, so the top-left corner does not open Overview
        configFile.kwinrc."Effect-overview".BorderActivate = 9;

        # Turn the screen off after ten idle minutes and require the password immediately on return
        kscreenlocker = {
          autoLock = true;
          timeout = 10;
          passwordRequiredDelay = 0;
          lockOnResume = true;
        };

        ## Part 4. Power
        # Never suspend long-running work on mains power, but suspend after twenty idle minutes on battery
        # Turn the display off after ten minutes and suspend when the lid closes
        # Hibernation is unavailable (docs/DISK.md)
        powerdevil = {
          AC = {
            autoSuspend.action = "nothing";
            turnOffDisplay.idleTimeout = 600;
            whenLaptopLidClosed = "sleep";
          };
          battery = {
            autoSuspend = {
              action = "sleep";
              idleTimeout = 1200;
            };
            turnOffDisplay.idleTimeout = 600;
            whenLaptopLidClosed = "sleep";
          };
        };
      };
    };
}
