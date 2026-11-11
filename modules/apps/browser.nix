# Brave with managed policies; hosts opt in by importing nixos.browser
{
  flake.modules.nixos.browser =
    { pkgs, ... }:
    {
      environment.systemPackages = [ pkgs.brave ];

      # programs.chromium writes the same managed policies for Chromium, Chrome and Brave (/etc/brave/policies/managed/)
      # Names follow Brave's policy templates: brave-core components/policy/resources/templates/policy_definitions
      programs.chromium = {
        enable = true;

        # Force-installed extensions are installed on first start and cannot be removed
        extensions = [
          "nngceckbapebfimnlniiiahkandclblb" # Bitwarden
        ];

        extraOpts = {
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
        };
      };
    };
}
