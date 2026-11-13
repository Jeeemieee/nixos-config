# Brave with managed policies; hosts opt in by importing nixos.browser
{
  flake.modules.nixos.browser =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      # The address bar searches through this machine's SearXNG where nixos.search runs it, and through Brave Search elsewhere
      # Brave Search: its own index, no tracking; the user prefers it to Startpage
      braveSearch = "https://search.brave.com/search?q={searchTerms}";
      searx = config.services.searx;
      localSearch = "http://${searx.settings.server.bind_address}:${toString searx.settings.server.port}/search?q={searchTerms}";

      # Starts Brave at login, unless it already runs
      # After a crash or a power loss Brave only offers "Restore pages?" in one empty window, whatever RestoreOnStartup says
      # Marking the last exit as normal makes it open the saved windows and tabs unasked; Brave is not running, so nothing else writes the file
      braveSession = pkgs.writeShellApplication {
        name = "brave-session";
        runtimeInputs = [
          pkgs.jq
          pkgs.procps
          pkgs.brave
        ];
        text = ''
          if pgrep -u "$(id -u)" -x brave > /dev/null; then
            exit 0
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
    in
    {
      environment.systemPackages = [ pkgs.brave ];

      # XDG autostart: every desktop session starts Brave through brave-session, which brings back the last windows and tabs
      environment.etc."xdg/autostart/brave-session.desktop".text = ''
        [Desktop Entry]
        Type=Application
        Name=Brave (restore the last session)
        Exec=${braveSession}/bin/brave-session
        Icon=brave-browser
      '';

      # programs.chromium writes the same managed policies for Chromium, Chrome and Brave (/etc/brave/policies/managed/)
      # Names follow Brave's policy templates: brave-core components/policy/resources/templates/policy_definitions
      programs.chromium = {
        enable = true;

        # Force-installed extensions are installed on first start and cannot be removed
        extensions = [
          "nngceckbapebfimnlniiiahkandclblb" # Bitwarden
          "ekhagklcjbdpajgpjgmbionohlpdbjgc" # Zotero Connector
          # KRunner lists the open tabs and selects one; its host program comes with Plasma (programs.chromium.enablePlasmaBrowserIntegration)
          "cimiefiiaegbelhefglklhhakcgmhkai" # Plasma Integration
        ];

        # No search suggestions are requested while typing
        defaultSearchProviderEnabled = true;
        defaultSearchProviderSearchURL = if searx.enable then localSearch else braveSearch;

        extraOpts = {
          DefaultSearchProviderName = if searx.enable then "SearXNG" else "Brave Search";
          # Keywords in the address bar: the keyword, a space, then the query; each searches that site directly, without SearXNG
          # A search that starts with one of these words and a space goes to that site as well
          SiteSearchSettings =
            lib.mapAttrsToList
              (shortcut: site: {
                inherit shortcut;
                inherit (site) name url;
              })
              {
                # Also the way to search while SearXNG is down or returns little
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
                # Takes a DOI or a paper's address; Sci-Hub changes its address now and then, so update it here when the keyword stops working
                scihub = {
                  name = "Sci-Hub";
                  url = "https://sci-hub.ru/{searchTerms}";
                };
              };
          # Spell checking in British English and Dutch
          SpellcheckEnabled = true;
          SpellcheckLanguage = [
            "en-GB"
            "nl"
          ];
          # Bitwarden is the only password manager
          PasswordManagerEnabled = false;
          BookmarkBarEnabled = true;
          ShowHomeButton = true;
          # Standard protection against phishing and malware downloads
          SafeBrowsingProtectionLevel = 1;
          BraveRewardsDisabled = true;
          BraveWalletDisabled = true;
          # Brave VPN is not built for Linux; the policy is accepted and keeps it off should that change
          BraveVPNDisabled = true;
          # Leo AI assistant
          BraveAIChatEnabled = false;
          # Brave's privacy-preserving usage statistics (P3A)
          BraveP3AEnabled = false;
          BraveStatsPingEnabled = false;
          BraveWebDiscoveryEnabled = false;
          # Chromium's usage statistics and crash reports
          MetricsReportingEnabled = false;

          # Open the windows and tabs of the last session at every start ("Continue where you left off")
          RestoreOnStartup = 1;
          # Memory Saver: tabs that have not been used for a while are unloaded and reload when selected
          HighEfficiencyModeEnabled = true;
          MemorySaverModeSavings = 1;
        };
      };
    };
}
