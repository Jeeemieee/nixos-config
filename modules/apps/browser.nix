# Brave with managed policies; hosts opt in by importing nixos.browser
{
  flake.modules.nixos.browser =
    { pkgs, ... }:
    let
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

        # Startpage: Google's results through a service that does not track; no search suggestions are requested while typing
        defaultSearchProviderEnabled = true;
        defaultSearchProviderSearchURL = "https://www.startpage.com/sp/search?query={searchTerms}";

        extraOpts = {
          DefaultSearchProviderName = "Startpage";
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
