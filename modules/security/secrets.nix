# Secret decryption identity
#
# What it is    sops-nix with one local age key, strict key permissions and an enrolment test module
# Who uses it   NixOS hosts by importing nixos.secrets; the test VM also imports nixos.secrets-test
# A host adds   Its public age recipient to the encrypted files in nixos-secrets before enabling real secrets
# Protected     Yes: this controls the private decryption key and secret activation (docs/SECRETS.md)
{ inputs, ... }@topLevel:
{
  ## Part 1. Shared sops-nix module
  flake.modules.nixos.secrets =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    {
      # Give repeated imports one identity so the module system does not concatenate these definitions
      key = "nixos-config#nixos.secrets";

      # Add sops-nix's secret options and activation support
      imports = [ inputs.sops-nix.nixosModules.sops ];

      sops = {
        # Use one generated age identity stored outside the Nix store
        age = {
          keyFile = "/var/lib/sops-nix/key.txt";

          # Generate the key through the hardened service below, including before any secret is enrolled
          generateKey = false;

          # Never reuse host SSH keys as secret-decryption identities
          sshKeyPaths = [ ];
        };
        # Never ask GnuPG to reuse SSH keys either
        gnupg.sshKeyPaths = [ ];

        # Install secrets through systemd after the local identity service is ready
        useSystemdActivation = true;
      };

      # Create and validate the machine identity even before any ciphertext includes its public recipient
      systemd.services.sops-age-key = {
        description = "Provision this machine's age identity";
        wantedBy = [ "sysinit.target" ];
        after = [ "local-fs.target" ];
        before = [
          "sysinit.target"
          "sops-install-secrets.service"
        ];
        requiredBy = lib.optional (config.sops.secrets != { }) "sops-install-secrets.service";
        unitConfig.DefaultDependencies = false;
        serviceConfig = {
          # Run once per boot and remain active as the dependency for secret installation
          Type = "oneshot";
          RemainAfterExit = true;
          # Let only root access newly created identity files and their directory
          StateDirectory = "sops-nix";
          StateDirectoryMode = "0700";
          UMask = "0077";
          # Restrict the small provisioning service to the state directory it needs
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

  ## Part 2. Enrolment test module
  flake.modules.nixos.secrets-test =
    { config, lib, ... }:
    {
      # Exercise the same identity provisioning as a real host
      imports = [ topLevel.config.flake.modules.nixos.secrets ];

      # Decrypt one harmless value only after the test host's public recipient is enrolled
      sops.secrets = {
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
