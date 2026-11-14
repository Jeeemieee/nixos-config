# Brave and Plasma session handover
#
# What it is    A logout wrapper that gives Brave time to save every window before Plasma ends
# Who uses it   The Home Manager desktop-kde module together with nixos.browser
# A user adds   Nothing; the browser module supplies Brave's matching restore policy and launcher
# Protected     No: this only coordinates two user applications during logout
{
  flake.modules.homeManager.desktop-kde =
    { pkgs, ... }:
    let
      # End Brave as one browser before handing the logout back to Plasma's own shutdown program
      # The main process has no --type argument and saves every window when it receives SIGTERM
      shutdownAfterBrave = pkgs.writeShellApplication {
        name = "plasma-shutdown-after-brave";
        runtimeInputs = [
          pkgs.procps
          pkgs.coreutils
        ];
        text = ''
          for pid in $(pgrep -u "$(id -u)" -x brave || true); do
            # Skips processes that ended in the meantime and Brave's helper processes
            if command=$({ tr '\0' ' ' < "/proc/$pid/cmdline"; } 2> /dev/null) && [[ "$command" != *--type=* ]]; then
              kill -TERM "$pid" 2> /dev/null || true
            fi
          done

          # At most 15 seconds, so that a hanging browser cannot keep the session from ending
          for _ in $(seq 1 75); do
            pgrep -u "$(id -u)" -x brave > /dev/null || break
            sleep 0.2
          done

          exec ${pkgs.kdePackages.plasma-workspace}/bin/plasma-shutdown "$@"
        '';
      };
    in
    {
      ## Part 1. Login behaviour
      # Start with an empty Plasma session so the user chooses which applications to open
      # Plasma's own restore would start Brave with an extra window beside the ones Brave restores
      programs.plasma.session.sessionRestore.restoreOpenApplicationsOnLogin = "startWithEmptySession";

      ## Part 2. Logout behaviour
      # Plasma normally closes Brave one window at a time, which loses single-tab windows and can delay logout
      # Replace Plasma's D-Bus shutdown entry with the wrapper so Brave first receives one whole-browser stop
      # This relies on Plasma internals, so test menu logout after updates
      # Removing the entry restores the default
      xdg.dataFile."dbus-1/services/org.kde.Shutdown.service".text = ''
        [D-BUS Service]
        Name=org.kde.Shutdown
        Exec=${shutdownAfterBrave}/bin/plasma-shutdown-after-brave
      '';
    };
}
