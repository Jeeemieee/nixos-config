# VPN clients
#
# What it is    Tailscale, Mullvad and eduVPN with the NetworkManager OpenVPN support eduVPN needs
# Who uses it   A NixOS host by importing nixos.vpn; the workstation profile imports it
# A host adds   Its Tailscale key in the host secrets file and one-time Mullvad login in the app
# Protected     No: private keys stay in the protected input and checks assert service ordering
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.vpn =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    {
      # Make the host's encrypted Tailscale key available to the service
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      ## Part 1. Tailscale
      # Join automatically with the host's encrypted key; without it, sudo tailscale up is the manual path
      services.tailscale = {
        # Start the private mesh VPN service
        enable = true;

        # Read the single-use join key from sops-nix's root-only path
        authKeyFile = config.sops.secrets.tailscale_authkey.path;
      };
      # Select the key encrypted specifically for this host
      sops.secrets.tailscale_authkey = {
        sopsFile = "${inputs.nixos-secrets}/secrets/${config.networking.hostName}.yaml";
      };

      # Make failed decryption fail automatic login rather than letting Tailscale start without its key
      systemd.services.tailscaled-autoconnect = {
        requires = [ "sops-install-secrets.service" ];
        after = [ "sops-install-secrets.service" ];
      };

      ## Part 2. Mullvad
      # Install the daemon with its desktop app rather than the command-line-only default package
      services.mullvad-vpn = {
        enable = true;
        package = pkgs.mullvad-vpn;
      };

      ## Part 3. eduVPN
      # Install eduVPN and the NetworkManager OpenVPN plugin required by its generated profiles
      environment.systemPackages = [ pkgs.eduvpn-client ];
      networking.networkmanager.plugins = [ pkgs.networkmanager-openvpn ];
    };
}
