# KDE Plasma settings for the user, declared with plasma-manager; users opt in by importing homeManager.desktop-kde
# Declared settings are applied at every login; settings that are not declared here keep what was chosen in System Settings
{ inputs, ... }:
{
  flake.modules.homeManager.desktop-kde =
    { lib, ... }:
    {
      imports = [ inputs.plasma-manager.homeModules.plasma-manager ];

      programs.plasma = {
        enable = true;

        workspace.lookAndFeel = "org.kde.breezedark.desktop";

        input.keyboard.numlockOnStartup = "on";

        # Plasma keeps its own copy of the language and formats per user, which overrides the system's when it differs
        configFile.plasma-localerc = {
          Formats = {
            LANG = "en_GB.UTF-8";
            # Named explicitly, so that a machine that had Dutch dates returns to English ones
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
          Translations.LANGUAGE = "en_GB";
        };

        # No overview when the pointer hits the top-left corner (9 is "no screen edge")
        configFile.kwinrc."Effect-overview".BorderActivate = 9;

        # The screen turns off after ten minutes without input and is locked at once; waking up asks for the password
        kscreenlocker = {
          autoLock = true;
          timeout = 10;
          passwordRequiredDelay = 0;
          lockOnResume = true;
        };

        # On mains power the machine never suspends by itself (simulations run for hours); on battery after twenty minutes
        # Closing the lid suspends; there is no hibernation (docs/DISK.md)
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
