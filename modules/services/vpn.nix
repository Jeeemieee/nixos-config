# VPN clients; hosts opt in by importing nixos.vpn
{
  flake.modules.nixos.vpn =
    { pkgs, ... }:
    {
      # Tailscale; log in once with `sudo tailscale up`
      services.tailscale.enable = true;

      # Mullvad daemon with its desktop app (the default package is the command line only); log in once in the app
      services.mullvad-vpn = {
        enable = true;
        package = pkgs.mullvad-vpn;
      };

      # eduVPN creates NetworkManager connections; OpenVPN profiles need NetworkManager's OpenVPN plugin
      environment.systemPackages = [ pkgs.eduvpn-client ];
      networking.networkmanager.plugins = [ pkgs.networkmanager-openvpn ];
    };
}
