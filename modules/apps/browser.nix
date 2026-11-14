# Web browser
#
# What it is    Brave with fixed privacy, search, extension and session settings
# Who uses it   A NixOS host by importing nixos.browser; the workstation profile imports it
# A host adds   nixos.search when the address bar should use the local SearXNG service
# Protected     No: browser choices do not control access, data recovery or the agent safeguards
{
  flake.modules.nixos.browser =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      ## Part 1. Search addresses
      # Brave Search has its own index and no tracking, and is preferred to Startpage
      braveSearch = "https://search.brave.com/search?q={searchTerms}";
      # Read the local service once so its address and enabled state stay together
      searx = config.services.searx;

      # Send address-bar searches to this machine when its private SearXNG service is enabled
      localSearch = "http://${searx.settings.server.bind_address}:${toString searx.settings.server.port}/search?q={searchTerms}";

      ## Part 2. Session recovery launcher
      # Route the application menu, task bar and links from other programs through one recovery-aware launcher
      # After a crash or power loss Brave otherwise opens one empty window and asks whether to restore pages
      # Change the saved exit to normal only while Brave is closed
      # This restores the saved windows without a prompt
      braveSession = pkgs.writeShellApplication {
        name = "brave-session";
        runtimeInputs = [
          pkgs.jq
          pkgs.procps
          pkgs.brave
        ];
        text = ''
          if pgrep -u "$(id -u)" -x brave > /dev/null; then
            exec brave "$@"
          fi

          for preferences in "''${XDG_CONFIG_HOME:-$HOME/.config}"/BraveSoftware/Brave-Browser/*/Preferences; do
            if [ -f "$preferences" ] && [ "$(jq -r '.profile.exit_type' "$preferences")" = "Crashed" ]; then
              jq -c '.profile.exit_type = "Normal"' "$preferences" > "$preferences.brave-session"
              mv "$preferences.brave-session" "$preferences"
            fi
          done

          exec brave "$@"
        '';
      };

      # Replace Brave's menu launchers with the recovery-aware launcher and give these copies priority
      # Do not start Brave at login; the saved session returns when the user chooses to open it
      braveLaunchers = lib.hiPrio (
        pkgs.runCommand "brave-launchers" { } ''
          mkdir -p "$out/share/applications"
          for launcher in ${pkgs.brave}/share/applications/*.desktop; do
            sed 's|^Exec=${pkgs.brave}/bin/brave|Exec=${braveSession}/bin/brave-session|' "$launcher" > "$out/share/applications/$(basename "$launcher")"
            # Fails the build when a launcher starts the browser in another way than this replacement expects
            if grep -q '^Exec=' "$out/share/applications/$(basename "$launcher")" && grep '^Exec=' "$out/share/applications/$(basename "$launcher")" | grep -qv '^Exec=${braveSession}/bin/brave-session'; then
              echo "brave-launchers: $(basename "$launcher") has an Exec line that was not replaced" >&2
              exit 1
            fi
          done
        ''
      );
    in
    {
      ## Part 3. Installed browser and launchers
      # Install Brave together with the higher-priority launchers that restore its session
      environment.systemPackages = [
        pkgs.brave
        braveLaunchers
      ];

      ## Part 4. Managed browser policy
      # Use Chromium's module because it writes Brave's managed policy directory too
      # Policy names follow Brave's policy templates under brave-core components/policy/resources/templates
      programs.chromium = {
        # Enable the module so the policy and extensions below are written for Brave
        enable = true;

        # Install the required extensions on first start and prevent accidental removal
        extensions = [
          "nngceckbapebfimnlniiiahkandclblb" # Bitwarden
          "ekhagklcjbdpajgpjgmbionohlpdbjgc" # Zotero Connector
          # Let KRunner list and select open tabs through Plasma's browser integration host
          "cimiefiiaegbelhefglklhhakcgmhkai" # Plasma Integration
        ];

        # Set a search address explicitly without enabling suggestions while typing
        defaultSearchProviderEnabled = true;

        # Prefer the private local search service and fall back to Brave Search on hosts without it
        defaultSearchProviderSearchURL = if searx.enable then localSearch else braveSearch;

        extraOpts = {
          # Show the name of the provider selected by the host's SearXNG setting
          DefaultSearchProviderName = if searx.enable then "SearXNG" else "Brave Search";

          # Keep direct site searches available as a keyword, a space and the query
          # These bypass SearXNG, and matching ordinary searches use the same shortcut
          SiteSearchSettings =
            lib.mapAttrsToList
              (shortcut: site: {
                inherit shortcut;
                inherit (site) name url;
              })
              {
                # Keep an independent search available when SearXNG is down or finds too little
                brave = {
                  name = "Brave Search";
                  url = braveSearch;
                };
                google = {
                  name = "Google";
                  url = "https://www.google.com/search?q={searchTerms}";
                };
                # SearXNG's Map tab searches OpenStreetMap; Google Maps cannot be included there
                maps = {
                  name = "Google Maps";
                  url = "https://www.google.com/maps/search/{searchTerms}";
                };
                reddit = {
                  name = "Reddit";
                  url = "https://www.reddit.com/search/?q={searchTerms}";
                };
                github = {
                  name = "GitHub";
                  url = "https://github.com/search?q={searchTerms}";
                };
                scholar = {
                  name = "Google Scholar";
                  url = "https://scholar.google.com/scholar?q={searchTerms}";
                };
                arxiv = {
                  name = "arXiv";
                  url = "https://arxiv.org/search/?searchtype=all&query={searchTerms}";
                };
                # Opens the paper that a DOI belongs to
                doi = {
                  name = "DOI";
                  url = "https://doi.org/{searchTerms}";
                };
                wiki = {
                  name = "Wikipedia";
                  url = "https://en.wikipedia.org/wiki/Special:Search?search={searchTerms}";
                };
                youtube = {
                  name = "YouTube";
                  url = "https://www.youtube.com/results?search_query={searchTerms}";
                };
                nixpkgs = {
                  name = "NixOS packages";
                  url = "https://search.nixos.org/packages?query={searchTerms}";
                };
                nixopt = {
                  name = "NixOS options";
                  url = "https://search.nixos.org/options?query={searchTerms}";
                };
                pypi = {
                  name = "PyPI";
                  url = "https://pypi.org/search/?q={searchTerms}";
                };
                # Accept a DOI or paper address; update this address when Sci-Hub moves and the shortcut stops
                scihub = {
                  name = "Sci-Hub";
                  url = "https://sci-hub.ru/{searchTerms}";
                };
              };
          # Check spelling in the two languages used on the workstation
          SpellcheckEnabled = true;
          SpellcheckLanguage = [
            "en-GB"
            "nl"
          ];
          # Prevent Brave from competing with Bitwarden for saved passwords
          PasswordManagerEnabled = false;
          # Keep bookmarks and the home action visible without opening their settings manually
          BookmarkBarEnabled = true;
          ShowHomeButton = true;

          # Use Brave's standard protection against phishing and malware downloads
          SafeBrowsingProtectionLevel = 1;
          # Remove cryptocurrency features that are not used
          BraveRewardsDisabled = true;
          BraveWalletDisabled = true;
          # Brave VPN is not built for Linux; the policy is accepted and keeps it off should that change
          BraveVPNDisabled = true;
          # Keep the unused Leo assistant out of the browser
          BraveAIChatEnabled = false;
          # Send no Brave usage statistics or discovery reports
          BraveP3AEnabled = false;
          BraveStatsPingEnabled = false;
          BraveWebDiscoveryEnabled = false;
          # Send no Chromium usage statistics or crash reports
          MetricsReportingEnabled = false;

          # Reopen the last windows and tabs at every normal start
          RestoreOnStartup = 1;
          # Unload tabs that have not been used for a while and reload them when selected
          HighEfficiencyModeEnabled = true;
          MemorySaverModeSavings = 1;
        };
      };
    };
}
