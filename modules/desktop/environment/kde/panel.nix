# The panel: pinned programs, system monitors, battery percentage and week numbers; the touchpad and the mouse
# Part of homeManager.desktop-kde, next to settings.nix and keyboard.nix
{
  flake.modules.homeManager.desktop-kde = {
    programs.plasma = {
      # Plasma's own panel with its usual parts, plus what is declared below; one on every screen
      panels = [
        {
          location = "bottom";
          screen = "all";
          widgets = [
            "org.kde.plasma.kickoff"
            "org.kde.plasma.pager"
            {
              iconTasks = {
                # Pinned programs, in this order; each is the name of its launcher file
                launchers = map (name: "applications:${name}.desktop") [
                  "brave-browser"
                  "thunderbird"
                  "org.kde.dolphin"
                  "org.kde.konsole"
                  "zotero"
                  "obsidian"
                  "org.kde.kate"
                  "codium"
                ];
                # A screen's panel lists the windows of that screen and of the desktop in view
                behavior.showTasks = {
                  onlyInCurrentScreen = true;
                  onlyInCurrentDesktop = true;
                };
              };
            }
            "org.kde.plasma.marginsseparator"
            # Processor, memory, network and disk activity as small line charts
            {
              systemMonitor = {
                title = "Processor";
                showTitle = false;
                showLegend = false;
                displayStyle = "org.kde.ksysguard.linechart";
                sensors = [
                  {
                    name = "cpu/all/usage";
                    color = "61,174,233";
                    label = "Processor %";
                  }
                ];
              };
            }
            {
              systemMonitor = {
                title = "Memory";
                showTitle = false;
                showLegend = false;
                displayStyle = "org.kde.ksysguard.linechart";
                sensors = [
                  {
                    name = "memory/physical/usedPercent";
                    color = "233,120,61";
                    label = "Memory %";
                  }
                ];
              };
            }
            {
              systemMonitor = {
                title = "Network";
                showTitle = false;
                showLegend = false;
                displayStyle = "org.kde.ksysguard.linechart";
                sensors = [
                  {
                    name = "network/all/download";
                    color = "61,233,140";
                    label = "Download";
                  }
                  {
                    name = "network/all/upload";
                    color = "233,61,174";
                    label = "Upload";
                  }
                ];
              };
            }
            {
              systemMonitor = {
                title = "Disk";
                showTitle = false;
                showLegend = false;
                displayStyle = "org.kde.ksysguard.linechart";
                sensors = [
                  {
                    name = "disk/all/read";
                    color = "233,201,61";
                    label = "Read";
                  }
                  {
                    name = "disk/all/write";
                    color = "155,89,182";
                    label = "Write";
                  }
                ];
              };
            }
            # The battery with its percentage, as a part of its own: plasma-manager cannot set up the one inside the system tray,
            # which therefore moves into the tray's pop-up
            {
              battery.showPercentage = true;
            }
            {
              systemTray.items.hidden = [ "org.kde.plasma.battery" ];
            }
            {
              digitalClock.calendar.showWeekNumbers = true;
            }
            "org.kde.plasma.showdesktop"
          ];
        }
      ];

      input = {
        # The laptop's own touchpad; Plasma keeps these settings per device
        touchpads = [
          {
            name = "VEN_0488:00 0488:1064 Touchpad";
            vendorId = "0488";
            productId = "1064";
            naturalScroll = true;
            tapToClick = true;
            disableWhileTyping = true;
            # A click in the bottom-right corner is a right click
            rightClickMethod = "bottomRight";
          }
        ];
        # The mouse on the 3Dconnexion receiver: no acceleration, a little slower than the default
        mice = [
          {
            name = "3Dconnexion 3Dconnexion Universal Receiver Mouse";
            vendorId = "256f";
            productId = "c652";
            accelerationProfile = "none";
            acceleration = -0.23;
          }
        ];
      };
    };
  };
}
