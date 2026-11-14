# Wi-Fi profiles
#
# What it is    NetworkManager profiles for eduroam and private WPA networks using encrypted substitutions
# Who uses it   A NixOS host by importing nixos.wifi; the workstation profile imports it
# A host adds   The shared wifi_env secret containing network names, identities and passwords
# Protected     No: this public module holds placeholders while private values stay in nixos-secrets
{ inputs, ... }@topLevel:
{
  flake.modules.nixos.wifi =
    { config, lib, ... }:
    let
      # Build a private WPA profile whose name and passphrase come from the decrypted environment file
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
      # Make the shared encrypted Wi-Fi environment file available before NetworkManager writes profiles
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # Decrypt the shared values used by every host's Wi-Fi profiles
      sops.secrets.wifi_env = {
        sopsFile = "${inputs.nixos-secrets}/secrets/shared.yaml";
      };

      ## Part 1. Declared NetworkManager profiles
      networking.networkmanager.ensureProfiles = {
        # Replace each $PLACEHOLDER below from the root-only decrypted file
        environmentFiles = [ config.sops.secrets.wifi_env.path ];
        profiles = {
          # Follow the university's published eduroam CAT profile
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
              # Expose only the anonymous outer identity before the encrypted tunnel exists
              anonymous-identity = "anonymous@utwente.nl";
              # Trust only the university RADIUS server under the pinned HARICA and GEANT certificate chain
              ca-cert = "${./certs/utwente-eduroam-ca.pem}";
              domain-suffix-match = "radius.utwente.nl";
            };
            ipv4.method = "auto";
            ipv6.method = "auto";
          };
          # Create the private pre-shared-key networks from placeholders rather than public names or passwords
          home = pskNetwork "home" "HOME";
          gebbeken = pskNetwork "gebbeken" "GEBBEKEN";
          hotspot = pskNetwork "hotspot" "HOTSPOT";
        };
      };

      ## Part 2. Secret ordering
      # Make failed decryption fail profile creation rather than writing empty network details
      systemd.services.NetworkManager-ensure-profiles = {
        requires = [ "sops-install-secrets.service" ];
        after = [ "sops-install-secrets.service" ];
      };
    };
}
