{
  inputs,
  ...
}:
{
  imports = [
    inputs.make-shell.flakeModules.default
  ];

  perSystem =
    { pkgs, ... }:
    {
      make-shells.default = {
        packages = [
          pkgs.deploy-rs
        ];
      };
    };

  flake =
    { lib, config, ... }:
    {
      # The isVM filter below keeps mimir-vm out of the deploy nodes, but it would also drop any
      # future VM-hosted server such as yggdrasil, so replace it with an explicit opt-in then
      deploy.nodes = lib.mapAttrs' (
        hostname: nixosConfiguration:
        let
          inherit (nixosConfiguration.pkgs.stdenv.hostPlatform) system;
          adminUser = builtins.head (builtins.attrNames (lib.filterAttrs (_: u: u.isAdmin) nixosConfiguration.config.hostSpec.users));
          sshPort = (nixosConfiguration.config.hostSpec.networking.ports.${hostname}.tcp.ssh or 22);
          networkingSecrets = nixosConfiguration.config.hostSpec.networking or {};
          hasPrimarySubnet = builtins.hasAttr "subnets" networkingSecrets && builtins.hasAttr "primary" networkingSecrets.subnets;
          subnet = if hasPrimarySubnet then networkingSecrets.subnets.primary else null;
          hostInSecrets = hasPrimarySubnet && builtins.hasAttr hostname subnet.hosts;
          host = if hostInSecrets then subnet.hosts.${hostname} else null;
        in
        {
          name = hostname;
          value = {
            inherit hostname;
            fastConnection = hostname == "twinpines";
            profiles.system = {
              sshUser = adminUser;
              sshOpts = [
                (lib.optionalString (host != null) "-o HostName=${host.ip}")
                "-p ${builtins.toString sshPort}"
              ];
              user = "root";
              sudo = "doas -u";
              remoteBuild = hostname != "twinpines";
              confirmTimeout = 300;
              path = inputs.deploy-rs.lib.${system}.activate.nixos nixosConfiguration;
            };
          };
        }
      ) (lib.filterAttrs (_: host: !host.config.hostSpec.isVM) config.nixosConfigurations);
    };
}
