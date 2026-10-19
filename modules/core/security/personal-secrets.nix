{ inputs, ... }@topLevel:
{
  flake.modules.nixos.secrets =
    { config, lib, pkgs, ... }:
    {
      imports = [ inputs.sops-nix.nixosModules.sops ];

      sops = {
        age = {
          keyFile = "/var/lib/sops-nix/key.txt";
          generateKey = false;
          sshKeyPaths = [ ];
        };
        gnupg.sshKeyPaths = [ ];
        useSystemdActivation = true;
      };

      # Bootstrap an identity even before a secret has been encrypted for this host
      systemd.services.sops-age-key = {
        description = "Provision this machine's age identity";
        wantedBy = [ "sysinit.target" ];
        after = [ "local-fs.target" ];
        before = [ "sysinit.target" "sops-install-secrets.service" ];
        requiredBy = lib.optional (config.sops.secrets != { }) "sops-install-secrets.service";
        unitConfig.DefaultDependencies = false;
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          StateDirectory = "sops-nix";
          StateDirectoryMode = "0700";
          UMask = "0077";
          ProtectSystem = "strict";
          ProtectHome = true;
          PrivateTmp = true;
          NoNewPrivileges = true;
        };
        script = ''
          if [ ! -e ${lib.escapeShellArg config.sops.age.keyFile} ]; then
            ${pkgs.age}/bin/age-keygen -o ${lib.escapeShellArg config.sops.age.keyFile}
          fi
          ${pkgs.age}/bin/age-keygen -y ${lib.escapeShellArg config.sops.age.keyFile} >/dev/null
        '';
      };

      # Allow local public-recipient inspection without exposing the private identity
      environment.systemPackages = [ pkgs.age ];
    };

  flake.modules.nixos.secrets-test =
    { config, lib, ... }:
    {
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # Enable only after this host's public recipient is in the pinned ciphertext
      sops.secrets = lib.mkIf config.hostSpec.hasSecrets {
        bootstrap-test = {
          sopsFile = "${inputs.nixos-secrets}/secrets/test.yaml";
          key = "message";
          owner = "root";
          group = "root";
          mode = "0400";
        };
      };
    };
}
