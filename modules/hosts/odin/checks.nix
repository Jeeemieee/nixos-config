# Odin host checks
#
# What it is    Exact configuration, complete-system and two-interface remote-access checks for odin
# Who uses it   nix flake check before the integrating worker accepts this host
# A maintainer adds A control whenever an odin policy gains another allowed behaviour
# Protected     Yes: these checks guard disk layout, incoming access, backup and the installed software
{
  config,
  inputs,
  lib,
  ...
}:
{
  perSystem =
    { pkgs, ... }:
    let
      ## Part 1. Generated private inputs for build and VM checks
      # Use real encrypted test ciphertext and throwaway SSH keys without adding production material
      testPrivate =
        pkgs.runCommand "odin-test-private"
          {
            nativeBuildInputs = [
              pkgs.age
              pkgs.openssh
              pkgs.sops
            ];
          }
          ''
            export HOME=$TMPDIR
            mkdir "$out"
            age-keygen -o "$out/age-key.txt" 2> /dev/null
            ssh-keygen -q -t ed25519 -N "" -f "$out/ssh-key"
            cat > secrets.yaml <<'EOF'
            restic_env: |
                RESTIC_REPOSITORY='rest:http://backup.invalid/odin/'
                RESTIC_REST_USERNAME='odin-test'
                RESTIC_REST_PASSWORD='odin-test'
            restic_password: odin-test
            tailscale_authkey: tskey-auth-test
            user_password_hash: '!'
            wifi_env: |
                EDUROAM_IDENTITY='test'
                EDUROAM_PASSWORD='test'
                HOME_SSID='test'
                HOME_PSK='test'
                GEBBEKEN_SSID='test'
                GEBBEKEN_PSK='test'
                HOTSPOT_SSID='test'
                HOTSPOT_PSK='test'
            EOF
            sops encrypt --age "$(age-keygen -y "$out/age-key.txt")" secrets.yaml > "$out/secrets.yaml"
          '';

      # Replace every deliberately absent production fact and private file only in checks
      testOverrides =
        { lib, pkgs, ... }:
        {
          hostSpec.odin = {
            systemDiskById = "/dev/disk/by-id/odin-test-disk";
            hostId = "9f3a2c17";
            networkDevices = [
              "test-ethernet"
              "test-wifi"
            ];
          };
          hostSpec.tailscaleSsh.authorizedKeysFile = lib.mkForce "${testPrivate}/ssh-key.pub";
          networking.hostId = lib.mkForce "9f3a2c17";
          # Install the generated key at runtime because sops-nix correctly refuses private keys in the store
          systemd.services.sops-age-key.script = lib.mkForce ''
            ${pkgs.coreutils}/bin/install -m 600 ${testPrivate}/age-key.txt /var/lib/sops-nix/key.txt
            ${pkgs.age}/bin/age-keygen -y /var/lib/sops-nix/key.txt > /dev/null
          '';
          sops.secrets =
            lib.genAttrs
              [
                "restic_env"
                "restic_password"
                "tailscale_authkey"
                "user_password_hash"
                "wifi_env"
              ]
              (_: {
                sopsFile = lib.mkForce "${testPrivate}/secrets.yaml";
              });
        };

      odin = config.flake.nixosConfigurations.odin;
      odinTest = odin.extendModules {
        modules = [
          testOverrides
          { hostSpec.disk.device = lib.mkForce "/dev/vda"; }
        ];
      };
    in
    {
      ## Part 2. Full system build with generated private inputs
      checks.odin-system = odinTest.config.system.build.toplevel;

      ## Part 3. Two-interface proof of the firewall boundary
      checks.odin-remote-access = pkgs.testers.runNixOSTest {
        name = "odin-remote-access";

        nodes.server =
          { lib, ... }:
          {
            imports = [ config.flake.modules.nixos.tailscale-ssh-server ];

            # Keep this proof focused on the firewall boundary; the full host build covers the desktop composition
            networking.hostName = "odin-remote-test";
            networking.firewall.enable = true;
            users.users.jeeemieee = {
              isNormalUser = true;
              uid = 1000;
            };
            hostSpec.tailscaleSsh.authorizedKeysFile = "${testPrivate}/ssh-key.pub";
            networking.useNetworkd = true;
            virtualisation.vlans = [
              1
              2
            ];
            systemd.network.links."10-tailscale0" = {
              matchConfig.OriginalName = "eth1";
              linkConfig.Name = "tailscale0";
            };
            networking.interfaces.tailscale0.ipv4.addresses = [
              {
                address = "192.168.10.1";
                prefixLength = 24;
              }
            ];
            networking.interfaces.eth2.ipv4.addresses = [
              {
                address = "192.168.20.1";
                prefixLength = 24;
              }
            ];
          };

        nodes.tailClient = {
          virtualisation.vlans = [ 1 ];
          networking.interfaces.eth1.ipv4.addresses = [
            {
              address = "192.168.10.2";
              prefixLength = 24;
            }
          ];
          environment.systemPackages = [
            pkgs.openssh
            pkgs.sshpass
          ];
        };

        nodes.lanClient = {
          virtualisation.vlans = [ 2 ];
          networking.interfaces.eth1.ipv4.addresses = [
            {
              address = "192.168.20.2";
              prefixLength = 24;
            }
          ];
          environment.systemPackages = [
            pkgs.netcat
            pkgs.openssh
            pkgs.sshpass
          ];
        };

        testScript = ''
          start_all()
          server.wait_for_unit("sshd.service")

          with subtest("the generated key logs in over tailscale0"):
              tailClient.succeed("install -m 600 ${testPrivate}/ssh-key /tmp/ssh-key")
              tailClient.succeed("ssh -i /tmp/ssh-key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null jeeemieee@192.168.10.1 true")

          with subtest("the ordinary LAN cannot reach port 22"):
              lanClient.fail("nc -z -w 2 192.168.20.1 22")

          with subtest("another key and a password are refused"):
              tailClient.fail("ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null jeeemieee@192.168.10.1 true")
              tailClient.fail("sshpass -p wrong ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null jeeemieee@192.168.10.1 true")
        '';
      };
    };
}
