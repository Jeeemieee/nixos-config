# Plasma panel and pointing devices
#
# What it is    The panel layout, pinned programs, system monitors, clock, touchpad and mouse behaviour
# Who uses it   The Home Manager desktop-kde module beside settings.nix and keyboard.nix
# A user adds   Nothing; device identifiers already match the workstation hardware
# Protected     No: these settings only arrange the desktop and its input devices
{
  flake.modules.homeManager.desktop-kde = {
    programs.plasma = {
      ## Part 1. Panel on every screen
      # Build one bottom panel per screen from Plasma's usual controls and the additions below
      panels = [
        {
          location = "bottom";
          screen = "all";
          widgets = [
            "org.kde.plasma.kickoff"
            "org.kde.plasma.pager"
            {
              iconTasks = {
                # Keep the most-used applications pinned in this order by their launcher file names
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
                # Show only windows on the panel's screen and the desktop currently in view
                behavior.showTasks = {
                  onlyInCurrentScreen = true;
                  onlyInCurrentDesktop = true;
                };
              };
            }
            "org.kde.plasma.marginsseparator"
            ## Part 2. Compact system monitors
            # Show processor, memory, network and disk activity as small line charts
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
            # Keep a visible battery percentage outside the tray
            # plasma-manager cannot configure the tray's built-in battery item
            # Hide that second item in the tray pop-up to avoid showing the battery twice
            {
              battery.showPercentage = true;
            }
            {
              systemTray.items.hidden = [ "org.kde.plasma.battery" ];
            }
            {
              # Show ISO week numbers used when planning dates
              digitalClock.calendar.showWeekNumbers = true;
            }
            "org.kde.plasma.showdesktop"
          ];
        }
      ];

      ## Part 3. Pointing devices
      input = {
        # Apply the preferred touchpad behaviour to the laptop's exact device
        touchpads = [
          {
            name = "VEN_0488:00 0488:1064 Touchpad";
            vendorId = "0488";
            productId = "1064";
            # Match touch movement to direct manipulation and allow light taps to click
            naturalScroll = true;
            tapToClick = true;

            # Prevent accidental pointer movement while typing
            disableWhileTyping = true;

            # Reserve the bottom-right corner for a right click
            rightClickMethod = "bottomRight";
          }
        ];
        # Keep the receiver mouse predictable with no acceleration and a slightly slower speed
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
