# Wi-Fi and eduroam profiles for NetworkManager; hosts opt in by importing nixos.wifi
# Network names, identities and passwords come from wifi_env in secrets/shared.yaml; this public file only holds placeholders
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.wifi =
    { config, lib, ... }:
    let
      # A WPA-PSK network whose SSID and passphrase are substituted from the environment file
      pskNetwork = id: var: {
        connection = {
          inherit id;
          type = "wifi";
        };
        wifi = {
          mode = "infrastructure";
          ssid = "$" + "${var}_SSID";
        };
        wifi-security = {
          key-mgmt = "wpa-psk";
          psk = "$" + "${var}_PSK";
        };
        ipv4.method = "auto";
        ipv6.method = "auto";
      };
    in
    {
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      sops.secrets.wifi_env = {
        sopsFile = "${inputs.nixos-secrets}/secrets/shared.yaml";
      };

      networking.networkmanager.ensureProfiles = {
        environmentFiles = [ config.sops.secrets.wifi_env.path ];
        profiles = {
          # University of Twente, from its official eduroam CAT profile (cat.eduroam.org, profile 770)
          eduroam = {
            connection = {
              id = "eduroam";
              type = "wifi";
            };
            wifi = {
              mode = "infrastructure";
              ssid = "eduroam";
            };
            wifi-security.key-mgmt = "wpa-eap";
            "802-1x" = {
              eap = "ttls";
              phase2-auth = "mschapv2";
              identity = "$EDUROAM_IDENTITY";
              password = "$EDUROAM_PASSWORD";
              # The real identity only travels inside the encrypted tunnel
              anonymous-identity = "anonymous@utwente.nl";
              # Only accept the university's RADIUS server, certified by HARICA through GEANT; this blocks fake eduroam access points
              ca-cert = "${./certs/utwente-eduroam-ca.pem}";
              domain-suffix-match = "radius.utwente.nl";
            };
            ipv4.method = "auto";
            ipv6.method = "auto";
          };
          home = pskNetwork "home" "HOME";
          gebbeken = pskNetwork "gebbeken" "GEBBEKEN";
          hotspot = pskNetwork "hotspot" "HOTSPOT";
        };
      };

      # sops-nix does not order its secrets before regular services; a failed decryption must fail this unit instead of writing empty profiles
      systemd.services.NetworkManager-ensure-profiles = {
        requires = [ "sops-install-secrets.service" ];
        after = [ "sops-install-secrets.service" ];
      };
    };
}
