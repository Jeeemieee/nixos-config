{ config, lib, ... }:
{
  perSystem = { pkgs, system, ... }:
    let
      # Must match the allowlist in modules/flake/nixpkgs.nix
      unfreeAllowed = [ "obsidian" "discord" "spotify" "zoom" "nvidia-x11" "nvidia-settings" "displaylink" ];

      # The policies of every personal workstation, for one host; they evaluate the configuration, they do not build it
      workstationPolicy =
        host:
        let
          cfg = host.config;
          user = cfg.home-manager.users.jeeemieee;
          vscode = user.programs.vscodium;
          editor = vscode.profiles.default;
          jupyter = lib.findSingle (extension: (extension.vscodeExtUniqueId or null) == "ms-toolsai.jupyter") null null editor.extensions;
          normalUsers = lib.filterAttrs (_: account: account.isNormalUser) cfg.users.users;
          bravePolicies = builtins.fromJSON cfg.environment.etc."brave/policies/managed/extra.json".text;
          braveDefaults = builtins.fromJSON cfg.environment.etc."brave/policies/managed/default.json".text;
          thunderbird = user.programs.thunderbird.profiles.default;
          wifiProfiles = cfg.networking.networkmanager.ensureProfiles.profiles;
          eduroam = wifiProfiles.eduroam."802-1x";
          userDirs = user.xdg.userDirs;
          unfreePackages = builtins.filter (package: package.meta.unfree or false) (cfg.environment.systemPackages ++ user.home.packages);
        in
        assert builtins.attrNames config.flake.nixosConfigurations == [ "mimir" "mimir-vm" ];
        assert !cfg.services.displayManager.autoLogin.enable;
        assert builtins.attrNames normalUsers == [ "jeeemieee" ];
        assert cfg.users.users.root.hashedPassword == "!";
        assert cfg.security.sudo.enable && cfg.security.sudo.wheelNeedsPassword;
        assert !cfg.services.openssh.enable;
        assert cfg.networking.firewall.enable;
        assert cfg.sops.age.keyFile == "/var/lib/sops-nix/key.txt";
        assert !cfg.sops.age.generateKey;
        assert cfg.sops.age.sshKeyPaths == [ ] && cfg.sops.gnupg.sshKeyPaths == [ ];
        assert cfg.sops.useSystemdActivation;
        assert cfg.systemd.services.sops-age-key.serviceConfig.StateDirectoryMode == "0700";
        assert cfg.systemd.services.sops-age-key.serviceConfig.UMask == "0077";
        assert cfg.home-manager.useGlobalPkgs && cfg.home-manager.useUserPackages;
        assert vscode.enable && !vscode.mutableExtensionsDir;
        assert vscode.package.pname == "vscodium";
        # The VS Code module would write VSCodium's configuration to VS Code's paths
        assert !user.programs.vscode.enable;
        assert builtins.all (extension: !(extension.meta.unfree or false)) editor.extensions;
        assert editor.userSettings."python.languageServer" == "None";
        assert editor.userSettings."basedpyright.analysis.typeCheckingMode" == "standard";
        assert editor.userSettings."telemetry.telemetryLevel" == "off";
        assert editor.userSettings."chat.disableAIFeatures";
        assert !editor.enableUpdateCheck && !editor.enableExtensionUpdateCheck;
        # The local Jupyter override must follow nixpkgs; a mismatch means the pinned version and hash need a bump
        assert jupyter != null && jupyter.version == pkgs.vscode-extensions.ms-toolsai.jupyter.version;
        assert cfg.programs.direnv.enable && cfg.programs.direnv.nix-direnv.enable;
        assert !user.programs.direnv.enable;
        assert lib.hasSuffix "@users.noreply.github.com" user.programs.git.settings.user.email;
        assert (cfg.environment.sessionVariables.NIXOS_OZONE_WL or null) == "1";
        # Login shells must load Home Manager's session variables, such as EDITOR
        assert lib.hasInfix "hm-session-vars.sh" cfg.environment.extraInit;
        # Brave's generated policy files: telemetry, AI and paid features off, Bitwarden force-installed
        assert (bravePolicies.BraveRewardsDisabled or null) == true && (bravePolicies.BraveWalletDisabled or null) == true;
        assert (bravePolicies.BraveVPNDisabled or null) == true && (bravePolicies.BraveAIChatEnabled or null) == false;
        assert (bravePolicies.BraveP3AEnabled or null) == false && (bravePolicies.BraveStatsPingEnabled or null) == false;
        assert (bravePolicies.BraveWebDiscoveryEnabled or null) == false && (bravePolicies.MetricsReportingEnabled or null) == false;
        assert builtins.elem "nngceckbapebfimnlniiiahkandclblb" (braveDefaults.ExtensionInstallForcelist or [ ]);
        # Thunderbird telemetry and studies off
        assert thunderbird.isDefault;
        assert (thunderbird.settings."toolkit.telemetry.enabled" or null) == false;
        assert (thunderbird.settings."datareporting.healthreport.uploadEnabled" or null) == false;
        assert (thunderbird.settings."datareporting.policy.dataSubmissionEnabled" or null) == false;
        assert (thunderbird.settings."app.shield.optoutstudies.enabled" or null) == false;
        assert user.xdg.configFile."mimeapps.list".force;
        # Docker is rootless only: no root daemon, and nobody in a docker group
        assert cfg.virtualisation.docker.rootless.enable && !cfg.virtualisation.docker.enable;
        assert (cfg.users.groups.docker.members or [ ]) == [ ];
        assert builtins.all (account: !(builtins.elem "docker" account.extraGroups)) (builtins.attrValues normalUsers);
        assert cfg.services.tailscale.enable && cfg.services.mullvad-vpn.enable;
        assert cfg.virtualisation.libvirtd.enable;
        # Tailscale joins with the host's key, and only after the secrets are installed
        assert cfg.services.tailscale.authKeyFile == cfg.sops.secrets.tailscale_authkey.path;
        assert builtins.elem "sops-install-secrets.service" cfg.systemd.services.tailscaled-autoconnect.requires;
        assert builtins.elem "sops-install-secrets.service" cfg.systemd.services.tailscaled-autoconnect.after;
        # eduroam follows the University of Twente's CAT profile: TTLS/MSCHAPv2, anonymous outer identity, pinned CA and server name
        assert wifiProfiles.eduroam.wifi.ssid == "eduroam" && wifiProfiles.eduroam.wifi-security.key-mgmt == "wpa-eap";
        assert eduroam.eap == "ttls" && eduroam.phase2-auth == "mschapv2";
        assert eduroam.anonymous-identity == "anonymous@utwente.nl";
        assert eduroam.domain-suffix-match == "radius.utwente.nl";
        assert lib.hasSuffix "utwente-eduroam-ca.pem" eduroam.ca-cert;
        assert eduroam.identity == "$EDUROAM_IDENTITY" && eduroam.password == "$EDUROAM_PASSWORD";
        # Network names and passphrases are placeholders filled from the decrypted environment file, never literal values
        assert builtins.attrNames wifiProfiles == [ "eduroam" "gebbeken" "home" "hotspot" ];
        assert builtins.all (name: lib.hasPrefix "$" wifiProfiles.${name}.wifi.ssid && lib.hasPrefix "$" wifiProfiles.${name}.wifi-security.psk) [ "gebbeken" "home" "hotspot" ];
        assert cfg.networking.networkmanager.ensureProfiles.environmentFiles == [ cfg.sops.secrets.wifi_env.path ];
        assert builtins.elem "sops-install-secrets.service" cfg.systemd.services.NetworkManager-ensure-profiles.requires;
        assert builtins.elem "sops-install-secrets.service" cfg.systemd.services.NetworkManager-ensure-profiles.after;
        # XDG user directories keep their usual names, in lowercase, and are created
        assert userDirs.enable && userDirs.createDirectories;
        assert builtins.all (dir: dir == "${user.home.homeDirectory}/${lib.toLower (baseNameOf dir)}" && dir == lib.toLower dir) (map (name: userDirs.${name}) [ "desktop" "documents" "download" "music" "pictures" "projects" "publicShare" "templates" "videos" ]);
        assert user.xdg.configFile."user-dirs.dirs".text != "";
        # pi is only installed as its sandboxed launcher, never as the bare package
        assert builtins.any (package: (package.name or "") == "pi") user.home.packages;
        assert !(builtins.elem pkgs.pi-coding-agent (cfg.environment.systemPackages ++ user.home.packages));
        # Defence in depth: even if the nixpkgs predicate is widened, only allowlisted unfree packages may be installed
        assert builtins.all (package: builtins.elem (lib.getName package) unfreeAllowed) unfreePackages;
        true;
    in
    lib.optionalAttrs (system == "x86_64-linux") {
      # The test VM: the workstation policies, and a launcher that shares nothing but the host's store
      checks.mimir-vm-config =
        let
          vm = config.flake.nixosConfigurations.mimir-vm.config;
        in
        assert workstationPolicy config.flake.nixosConfigurations.mimir-vm;
        assert vm.virtualisation.forwardPorts == [ ];
        assert builtins.attrNames vm.virtualisation.sharedDirectories == [ "nix-store" ];
        assert vm.virtualisation.sharedDirectories.nix-store.source == "/nix/store";
        assert builtins.elem "ro" vm.fileSystems."/nix/.ro-store".options;
        assert !vm.virtualisation.writableStoreUseTmpfs;
        assert vm.home-manager.users.jeeemieee.systemd.user.services ? mimir-vm-display;
        assert vm.users.users.jeeemieee.initialPassword == "mimir";
        pkgs.runCommand "mimir-vm-config-check" { } ''
          touch "$out"
        '';

      # The laptop: the workstation policies, the login password from secrets, the encrypted disk, Secure Boot and its hardware
      checks.mimir-config =
        let
          mimir = config.flake.nixosConfigurations.mimir.config;
          account = mimir.users.users.jeeemieee;
        in
        assert workstationPolicy config.flake.nixosConfigurations.mimir;
        # The password comes from nixos-secrets only, and accounts cannot be changed outside the configuration
        assert !mimir.users.mutableUsers;
        assert account.hashedPasswordFile == mimir.sops.secrets.user_password_hash.path;
        assert mimir.sops.secrets.user_password_hash.neededForUsers;
        assert account.initialPassword == null && account.password == null && account.hashedPassword == null;
        assert builtins.attrNames mimir.sops.secrets == [ "tailscale_authkey" "user_password_hash" "wifi_env" ];
        assert lib.hasSuffix "/secrets/mimir.yaml" mimir.sops.secrets.tailscale_authkey.sopsFile;
        # Everything but the EFI partition is encrypted: ZFS inside LUKS, swap with a random key
        assert builtins.attrNames mimir.boot.initrd.luks.devices == [ "crypt" ];
        assert builtins.attrNames mimir.fileSystems == [ "/" "/boot" "/home" "/home/jeeemieee/scratch" "/nix" ];
        assert builtins.all (path: mimir.fileSystems.${path}.fsType == "zfs") [ "/" "/nix" "/home" "/home/jeeemieee/scratch" ];
        assert mimir.swapDevices != [ ] && builtins.all (swap: swap.randomEncryption.enable) mimir.swapDevices;
        assert !mimir.boot.zfs.forceImportRoot;
        assert mimir.networking.hostId != null;
        # Secure Boot: lanzaboote signs the boot files with keys generated on the machine, Microsoft's keys stay enrolled
        assert mimir.boot.lanzaboote.enable && !mimir.boot.loader.systemd-boot.enable;
        assert mimir.boot.lanzaboote.pkiBundle == "/var/lib/sbctl";
        assert mimir.boot.lanzaboote.autoGenerateKeys.enable && mimir.boot.lanzaboote.autoEnrollKeys.enable;
        assert mimir.boot.lanzaboote.autoEnrollKeys.includeMicrosoftKeys && !mimir.boot.lanzaboote.autoEnrollKeys.allowBrickingMyMachine;
        # Hardware: NVIDIA on demand with the open kernel modules, the DisplayLink dock, Bluetooth, disk monitoring
        assert mimir.hardware.nvidia.open && mimir.hardware.nvidia.prime.offload.enable;
        assert mimir.hardware.nvidia.prime.intelBusId == "PCI:0:2:0" && mimir.hardware.nvidia.prime.nvidiaBusId == "PCI:1:0:0";
        assert builtins.all (driver: builtins.elem driver mimir.services.xserver.videoDrivers) [ "nvidia" "displaylink" ];
        assert mimir.hardware.bluetooth.enable && mimir.services.smartd.enable;
        pkgs.runCommand "mimir-config-check" { } ''
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

      # The eduroam CA bundle must be exactly the root and intermediate from the University of Twente's CAT profile (cat.eduroam.org, profile 770)
      checks.mimir-vm-eduroam-ca =
        pkgs.runCommand "mimir-vm-eduroam-ca-check" { nativeBuildInputs = [ pkgs.openssl ]; } ''
          bundle=${config.flake.nixosConfigurations.mimir-vm.config.networking.networkmanager.ensureProfiles.profiles.eduroam."802-1x".ca-cert}
          # One file per certificate; comment lines between them are skipped
          awk '/-----BEGIN CERTIFICATE-----/ { n++; file = "cert-" n } file { print > file } /-----END CERTIFICATE-----/ { file = "" }' "$bundle"
          for cert in cert-*; do
            openssl x509 -in "$cert" -noout -fingerprint -sha256 | cut -d= -f2
          done | sort > actual
          printf '%s\n' \
            5B:67:8D:C4:40:95:A5:28:95:B6:3B:31:F2:72:27:F4:B3:6C:3E:34:74:91:BF:2B:FA:69:18:37:A5:FB:8C:79 \
            D9:5D:0E:8E:DA:79:52:5B:F9:BE:B1:1B:14:D2:10:0D:32:94:98:5F:0C:62:D9:FA:BD:9C:D9:99:EC:CB:7B:1D \
            | sort > expected
          diff expected actual
          touch "$out"
        '';

      # Build the system closures; `nix flake check` otherwise only evaluates the configurations
      checks.mimir-vm-system = config.flake.nixosConfigurations.mimir-vm.config.system.build.toplevel;
      checks.mimir-system = config.flake.nixosConfigurations.mimir.config.system.build.toplevel;

      # Validate the enabled secret and retain coverage of the enrollment-only mode
      checks.mimir-vm-secrets =
        let
          vm = config.flake.nixosConfigurations.mimir-vm.config;
          bootstrap = (config.flake.nixosConfigurations.mimir-vm.extendModules {
            modules = [ { hostSpec.hasSecrets = lib.mkForce false; } ];
          }).config;
          secret = vm.sops.secrets.bootstrap-test;
          # sops-nix expresses root either by name or, by default, as owner/group null with uid/gid 0
          rootOnly = s: (s.owner == "root" || (s.owner == null && s.uid == 0)) && (s.group == "root" || (s.group == null && s.gid == 0)) && s.mode == "0400";
        in
        assert builtins.attrNames vm.sops.secrets == [ "bootstrap-test" "tailscale_authkey" "wifi_env" ];
        # Per-host secrets come from secrets/<hostname>.yaml, shared ones from secrets/shared.yaml
        assert lib.hasSuffix "/secrets/mimir-vm.yaml" vm.sops.secrets.tailscale_authkey.sopsFile && vm.sops.secrets.tailscale_authkey.key == "tailscale_authkey";
        assert lib.hasSuffix "/secrets/shared.yaml" vm.sops.secrets.wifi_env.sopsFile && vm.sops.secrets.wifi_env.key == "wifi_env";
        assert rootOnly vm.sops.secrets.tailscale_authkey && rootOnly vm.sops.secrets.wifi_env;
        assert secret.key == "message";
        assert secret.owner == "root" && secret.group == "root";
        assert secret.mode == "0400";
        assert secret.path == "/run/secrets/bootstrap-test";
        assert vm.systemd.services.sops-age-key.requiredBy == [ "sops-install-secrets.service" ];
        assert builtins.elem "sops-install-secrets.service" vm.systemd.services.sops-age-key.before;
        assert bootstrap.sops.secrets == { };
        # Without secrets, Tailscale falls back to its documented manual login and nixos.wifi refuses explicitly
        assert bootstrap.services.tailscale.authKeyFile == null;
        assert builtins.any (a: !a.assertion && lib.hasPrefix "nixos.wifi needs hostSpec.hasSecrets" a.message) bootstrap.assertions;
        assert !(bootstrap.systemd.services ? sops-install-secrets);
        assert bootstrap.systemd.services.sops-age-key.requiredBy == [ ];
        vm.system.build.sops-nix-manifest;
    };
}
