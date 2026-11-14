# VPN clients; hosts opt in by importing nixos.vpn
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.vpn =
    { config, lib, pkgs, ... }:
    {
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # Tailscale joins with the host's auth key from secrets/<hostname>.yaml; without secrets, log in once with `sudo tailscale up`
      services.tailscale = {
        enable = true;
        authKeyFile = config.sops.secrets.tailscale_authkey.path;
      };
      sops.secrets.tailscale_authkey = {
        sopsFile = "${inputs.nixos-secrets}/secrets/${config.networking.hostName}.yaml";
      };

      # sops-nix does not order its secrets before regular services; a failed decryption must fail this unit instead of logging in without a key
      systemd.services.tailscaled-autoconnect = {
        requires = [ "sops-install-secrets.service" ];
        after = [ "sops-install-secrets.service" ];
      };

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
