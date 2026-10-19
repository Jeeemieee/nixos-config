{ config, lib, ... }:
{
  perSystem = { pkgs, system, ... }:
    lib.optionalAttrs (system == "x86_64-linux") {
      # Policy checks: these evaluate the configuration, they do not build it
      checks.mimir-vm-config =
        let
          vm = config.flake.nixosConfigurations.mimir-vm.config;
          user = vm.home-manager.users.jeeemieee;
          vscode = user.programs.vscode;
          normalUsers = lib.filterAttrs (_: account: account.isNormalUser) vm.users.users;
        in
        assert builtins.attrNames config.flake.nixosConfigurations == [ "mimir-vm" ];
        assert config.flake.deploy.nodes == { };
        assert !vm.services.displayManager.autoLogin.enable;
        assert builtins.attrNames normalUsers == [ "jeeemieee" ];
        assert vm.users.users.root.hashedPassword == "!";
        assert vm.security.sudo.enable && vm.security.sudo.wheelNeedsPassword;
        assert !vm.services.openssh.enable;
        assert vm.networking.firewall.enable;
        assert vm.sops.age.keyFile == "/var/lib/sops-nix/key.txt";
        assert !vm.sops.age.generateKey;
        assert vm.sops.age.sshKeyPaths == [ ] && vm.sops.gnupg.sshKeyPaths == [ ];
        assert vm.sops.useSystemdActivation;
        assert vm.systemd.services.sops-age-key.serviceConfig.StateDirectoryMode == "0700";
        assert vm.systemd.services.sops-age-key.serviceConfig.UMask == "0077";
        assert vm.virtualisation.forwardPorts == [ ];
        assert builtins.attrNames vm.virtualisation.sharedDirectories == [ "nix-store" ];
        assert vm.virtualisation.sharedDirectories.nix-store.source == "/nix/store";
        assert builtins.elem "ro" vm.fileSystems."/nix/.ro-store".options;
        assert !vm.virtualisation.writableStoreUseTmpfs;
        assert user.systemd.user.services ? mimir-vm-display;
        assert vm.home-manager.useGlobalPkgs && vm.home-manager.useUserPackages;
        assert vscode.enable && !vscode.mutableExtensionsDir;
        assert lib.hasSuffix "@users.noreply.github.com" user.programs.git.settings.user.email;
        pkgs.runCommand "mimir-vm-config-check" { } ''
          touch "$out"
        '';

      # Build the system closure; `nix flake check` otherwise only evaluates the configuration
      checks.mimir-vm-system = config.flake.nixosConfigurations.mimir-vm.config.system.build.toplevel;

      # Validate the enabled secret and retain coverage of the enrollment-only mode
      checks.mimir-vm-secrets =
        let
          vm = config.flake.nixosConfigurations.mimir-vm.config;
          bootstrap = (config.flake.nixosConfigurations.mimir-vm.extendModules {
            modules = [ { hostSpec.hasSecrets = lib.mkForce false; } ];
          }).config;
          secret = vm.sops.secrets.bootstrap-test;
        in
        assert builtins.attrNames vm.sops.secrets == [ "bootstrap-test" ];
        assert secret.key == "message";
        assert secret.owner == "root" && secret.group == "root";
        assert secret.mode == "0400";
        assert secret.path == "/run/secrets/bootstrap-test";
        assert vm.systemd.services.sops-age-key.requiredBy == [ "sops-install-secrets.service" ];
        assert builtins.elem "sops-install-secrets.service" vm.systemd.services.sops-age-key.before;
        assert bootstrap.sops.secrets == { };
        assert !(bootstrap.systemd.services ? sops-install-secrets);
        assert bootstrap.systemd.services.sops-age-key.requiredBy == [ ];
        vm.system.build.sops-nix-manifest;
    };
}
