# Lets Brave bring back every window after a logout, restart or shutdown from Plasma
# Part of homeManager.desktop-kde; the start at login and the restore policy are in nixos.browser (modules/apps/browser.nix)
{
  flake.modules.homeManager.desktop-kde =
    { pkgs, ... }:
    let
      # Lets Brave exit as a whole before Plasma ends the session, then hands over to Plasma's own plasma-shutdown
      # The browser process is the one without --type; it saves every window when it receives SIGTERM
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
      # No application reopens at login by itself; the user opens what he needs, and Brave then brings back its own windows
      # Plasma's own session restore would start Brave at login, with an extra window next to the ones Brave restores
      programs.plasma.session.sessionRestore.restoreOpenApplicationsOnLogin = "startWithEmptySession";

      # Plasma ends a session by asking every window to close. Brave takes that as the user closing its windows one by one:
      # it forgets the windows with a single tab and asks for confirmation in the others, which holds up the logout for two minutes
      # Plasma starts plasma-shutdown through D-Bus when a logout, restart or shutdown begins; this entry in the user's folder takes precedence over Plasma's
      # Relies on Plasma internals: test a logout from the menu after every Plasma update; removing this entry restores Plasma's default
      xdg.dataFile."dbus-1/services/org.kde.Shutdown.service".text = ''
        [D-BUS Service]
        Name=org.kde.Shutdown
        Exec=${shutdownAfterBrave}/bin/plasma-shutdown-after-brave
      '';
    };
}
