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
          editor = vscode.profiles.default;
          jupyter = lib.findSingle (extension: (extension.vscodeExtUniqueId or null) == "ms-toolsai.jupyter") null null editor.extensions;
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
        assert vscode.package.pname == "vscodium";
        assert builtins.all (extension: !(extension.meta.unfree or false)) editor.extensions;
        assert editor.userSettings."python.languageServer" == "None";
        assert editor.userSettings."basedpyright.analysis.typeCheckingMode" == "standard";
        assert editor.userSettings."telemetry.telemetryLevel" == "off";
        assert editor.userSettings."chat.disableAIFeatures";
        assert !editor.enableUpdateCheck && !editor.enableExtensionUpdateCheck;
        # The local Jupyter override must follow nixpkgs; a mismatch means the pinned version and hash need a bump
        assert jupyter != null && jupyter.version == pkgs.vscode-extensions.ms-toolsai.jupyter.version;
        assert vm.programs.direnv.enable && vm.programs.direnv.nix-direnv.enable;
        assert !user.programs.direnv.enable;
        assert lib.hasSuffix "@users.noreply.github.com" user.programs.git.settings.user.email;
        pkgs.runCommand "mimir-vm-config-check" { } ''
          touch "$out"
        '';

      # Every native binary in the VM user's extensions must be x86-64 and loadable from the Nix store
      checks.mimir-vm-editor-binaries =
        let
          user = config.flake.nixosConfigurations.mimir-vm.config.home-manager.users.jeeemieee;
          extensions = user.home.file.".vscode-oss/extensions".source;
        in
        pkgs.runCommand "mimir-vm-editor-binaries-check"
          {
            nativeBuildInputs = [
              pkgs.file
              pkgs.nodejs
              pkgs.glibc.bin
            ];
          }
          ''
            extensions=${extensions}
            jupyter="$extensions/ms-toolsai.jupyter"
            failed=0
            elfFiles=0

            # Jupyter's temp link points to /tmp, outside the store, so it is not followed
            find -L "$extensions" -path "$jupyter/temp" -prune -o -type f -exec file -L -0 {} + > files
            find -L "$extensions" -path "$jupyter/temp" -prune -o -type f -name '*.node' -print > node-files

            # 1. Every ELF file is x86-64
            while IFS= read -r -d "" path && IFS= read -r description; do
              case "$description" in
                *"ELF "*"x86-64"*) elfFiles=$((elfFiles + 1)) ;;
                *"ELF "*) elfFiles=$((elfFiles + 1)); echo "FAIL (architecture): $path$description"; failed=1 ;;
              esac
            done < files

            # 2. The x86-64 glibc ZeroMQ library is present
            if [ ! -f "$jupyter/dist/node_modules/zeromq/prebuilds/linux-x64/node.napi.glibc.node" ]; then
              echo "FAIL (zeromq): linux-x64 glibc ZeroMQ library is missing"
              failed=1
            fi

            # 3. Every Node add-on resolves its libraries
            while IFS= read -r path; do
              if ! ldd "$path" > ldd.out 2>&1 || grep -q 'not found' ldd.out; then
                echo "FAIL (ldd): $path"
                cat ldd.out
                failed=1
              fi
            done < node-files

            # 4. Node loads Jupyter's ZeroMQ binding
            if ! node -e 'require(process.argv[1])' "$jupyter/dist/node_modules/zeromq"; then
              echo "FAIL (require): node cannot load Jupyter's ZeroMQ binding"
              failed=1
            fi

            [ "$failed" = 0 ]
            echo "$elfFiles ELF files and $(wc -l < node-files) Node add-ons checked"
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
