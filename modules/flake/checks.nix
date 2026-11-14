# Configuration policy checks
#
# What it is    Evaluation assertions and build checks for both hosts and their shared workstation policy
# Who uses it   nix flake check through the checks.x86_64-linux outputs defined here
# A maintainer adds A pre-declared assertion or build check whenever a protected invariant needs coverage
# Protected     Yes: weakening these checks would remove safeguards described in docs/UPKEEP.md
{
  inputs,
  config,
  lib,
  ...
}:
{
  perSystem =
    { pkgs, options, ... }:
    let
      ## Part 1. Protected-setting ownership
      # Require safety and agent-control settings to come only from config-tool/protected.nix paths
      # Nix merges every module, so an ordinary module could otherwise set the same options
      # The module system reports this repository's defining file
      # Definitions from inputs remain outside this ownership policy
      protectedPaths = (import ../../config-tool/protected.nix).nixos-config;

      # Treat a protected folder as protecting every path below it
      isProtected =
        file: builtins.any (path: file == path || lib.hasPrefix "${path}/" file) protectedPaths;

      # Reduce each defining location to its repository-relative file and remove duplicates
      ownFiles =
        option:
        lib.unique (
          map (
            file: builtins.head (lib.splitString ", via option " (lib.removePrefix "${inputs.self}/" file))
          ) (builtins.filter (lib.hasPrefix "${inputs.self}/") (map toString option.files))
        );
      # Name every guarded option defined by an unprotected file and skip options absent from a host
      unprotectedDefinitions =
        allOptions: names:
        lib.concatMap (
          name:
          let
            path = lib.splitString "." name;
          in
          lib.optionals (lib.hasAttrByPath path allOptions) (
            map (file: "${name} in ${file}") (
              builtins.filter (file: !isProtected file) (ownFiles (lib.getAttrFromPath path allOptions))
            )
          )
        ) names;
      # Guard system options that control access, data, privileged code or every user shell
      guardedSystemOptions = [
        # The backup, and what it runs as
        "services.restic.backups"
        # What can reach the machine
        "networking.firewall.enable"
        "networking.firewall.allowedTCPPorts"
        "networking.firewall.allowedUDPPorts"
        "networking.firewall.allowedTCPPortRanges"
        "networking.firewall.allowedUDPPortRanges"
        "networking.firewall.trustedInterfaces"
        "networking.firewall.interfaces"
        "networking.firewall.extraCommands"
        "services.openssh.enable"
        # Who is who, and who becomes root
        "users.users"
        "users.groups"
        "users.mutableUsers"
        "security.sudo.enable"
        "security.sudo.wheelNeedsPassword"
        "security.sudo.extraRules"
        "security.sudo.extraConfig"
        "security.wrappers"
        "security.pam.services"
        "security.polkit.extraConfig"
        # The Nix daemon, which every sandbox reaches, and which packages exist
        "nix.settings"
        "nix.extraOptions"
        "nixpkgs.overlays"
        "nixpkgs.config"
        "nixpkgs.pkgs"
        # Where the secrets' key is
        "sops.age.keyFile"
        "sops.age.generateKey"
        "sops.age.sshKeyPaths"
        "sops.defaultSopsFile"
        # Disk, boot, and what runs as root when the system is activated
        "fileSystems"
        "swapDevices"
        "boot.initrd.luks.devices"
        "boot.kernelParams"
        "services.sanoid.datasets"
        "system.activationScripts"
        # What every shell of the user runs, outside any sandbox
        "environment.extraInit"
        "environment.shellInit"
        "programs.bash.interactiveShellInit"
        "programs.direnv.direnvrcExtra"
        # The user's own settings as a whole
        "home-manager.users"
        "home-manager.sharedModules"
      ];
      # Guard user options through which Git or SSH can execute code
      guardedUserOptions = [
        # The commit guard's hook, and where git and ssh run programs
        "programs.git.includes"
        "programs.git.hooks"
        "programs.git.settings"
        "programs.ssh.settings"
        "programs.ssh.includes"
        "programs.ssh.extraConfig"
      ];
      # Guard the checks, runnable programs, shells, formatter and package arguments exposed by the flake
      guardedFlakeOptions = [
        "checks"
        "packages"
        "apps"
        "devShells"
        "formatter"
        "_module.args"
      ];
      # Collect every ownership violation for one host into the assertion message below
      guardedSettings =
        host:
        unprotectedDefinitions host.options guardedSystemOptions
        ++ unprotectedDefinitions host.options.home-manager.users.valueMeta.attrs.jeeemieee.configuration.options guardedUserOptions
        ++ unprotectedDefinitions options guardedFlakeOptions;
      # Repeat nixpkgs.nix's allowlist as defence in depth against a widened package predicate
      unfreeAllowed = [
        "obsidian"
        "discord"
        "spotify"
        "zoom"
        "nvidia-x11"
        "nvidia-settings"
        "displaylink"
      ];

      ## Part 2. Shared workstation policy
      # Evaluate the agreed workstation invariants for one host without building its closure
      workstationPolicy =
        host:
        let
          # Use short names for the parts inspected repeatedly below
          cfg = host.config;
          user = cfg.home-manager.users.jeeemieee;
          vscode = user.programs.vscodium;
          editor = vscode.profiles.default;
          jupyter = lib.findSingle (
            extension: (extension.vscodeExtUniqueId or null) == "ms-toolsai.jupyter"
          ) null null editor.extensions;
          normalUsers = lib.filterAttrs (_: account: account.isNormalUser) cfg.users.users;
          bravePolicies = builtins.fromJSON cfg.environment.etc."brave/policies/managed/extra.json".text;
          braveDefaults = builtins.fromJSON cfg.environment.etc."brave/policies/managed/default.json".text;
          thunderbird = user.programs.thunderbird.profiles.default;
          wifiProfiles = cfg.networking.networkmanager.ensureProfiles.profiles;
          eduroam = wifiProfiles.eduroam."802-1x";
          userDirs = user.xdg.userDirs;
          unfreePackages = builtins.filter (package: package.meta.unfree or false) (
            cfg.environment.systemPackages ++ user.home.packages
          );
          piFile = name: user.home.file.".pi/agent/${name}";
          # Remove Nix's store-path context because fromJSON accepts only plain text
          piSettings = builtins.fromJSON (builtins.unsafeDiscardStringContext (piFile "settings.json").text);
        in
        assert
          builtins.attrNames config.flake.nixosConfigurations == [
            "mimir"
            "mimir-vm"
          ];
        assert !cfg.services.displayManager.autoLogin.enable;
        assert builtins.attrNames normalUsers == [ "jeeemieee" ];
        assert cfg.users.users.root.hashedPassword == "!";
        assert cfg.security.sudo.enable && cfg.security.sudo.wheelNeedsPassword;
        assert !cfg.services.openssh.enable;
        assert cfg.networking.firewall.enable;
        # Keep every incoming port closed and trust only the machine's loopback interface
        assert
          cfg.networking.firewall.allowedTCPPorts == [ ] && cfg.networking.firewall.allowedUDPPorts == [ ];
        assert
          cfg.networking.firewall.allowedTCPPortRanges == [ ]
          && cfg.networking.firewall.allowedUDPPortRanges == [ ];
        assert
          cfg.networking.firewall.interfaces == { } && cfg.networking.firewall.trustedInterfaces == [ "lo" ];
        # A trusted user of the Nix daemon is as good as root, and every pi sandbox reaches the daemon
        assert cfg.nix.settings.trusted-users == [ "root" ];
        assert lib.assertMsg (guardedSettings host == [ ])
          "guarded settings are defined by files that are not protected (config-tool/protected.nix): ${lib.concatStringsSep "; " (guardedSettings host)}";
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
        # Keep the local Jupyter correction at nixpkgs' version so a mismatch demands a reviewed hash update
        assert jupyter != null && jupyter.version == pkgs.vscode-extensions.ms-toolsai.jupyter.version;
        assert cfg.programs.direnv.enable && cfg.programs.direnv.nix-direnv.enable;
        assert !user.programs.direnv.enable;
        assert lib.hasSuffix "@users.noreply.github.com" user.programs.git.settings.user.email;
        assert (cfg.environment.sessionVariables.NIXOS_OZONE_WL or null) == "1";
        # Login shells must load Home Manager's session variables, such as EDITOR
        assert lib.hasInfix "hm-session-vars.sh" cfg.environment.extraInit;
        # Brave's generated policy files: telemetry, AI and paid features off, Bitwarden force-installed
        assert
          (bravePolicies.BraveRewardsDisabled or null) == true
          && (bravePolicies.BraveWalletDisabled or null) == true;
        assert
          (bravePolicies.BraveVPNDisabled or null) == true
          && (bravePolicies.BraveAIChatEnabled or null) == false;
        assert
          (bravePolicies.BraveP3AEnabled or null) == false
          && (bravePolicies.BraveStatsPingEnabled or null) == false;
        assert
          (bravePolicies.BraveWebDiscoveryEnabled or null) == false
          && (bravePolicies.MetricsReportingEnabled or null) == false;
        assert builtins.elem "nngceckbapebfimnlniiiahkandclblb" (
          braveDefaults.ExtensionInstallForcelist or [ ]
        );
        # Keep Bitwarden as the only password manager while retaining phishing protection
        assert
          (bravePolicies.PasswordManagerEnabled or null) == false
          && (bravePolicies.SafeBrowsingProtectionLevel or null) == 1;
        # Send address-bar searches to the machine's loopback-only SearXNG
        # Keep Brave Search available through its direct keyword
        assert cfg.services.searx.enable && cfg.services.searx.settings.server.bind_address == "127.0.0.1";
        assert lib.hasPrefix "http://127.0.0.1:${toString cfg.services.searx.settings.server.port}/search?"
          (braveDefaults.DefaultSearchProviderSearchURL or "");
        assert lib.all
          (keyword: builtins.elem keyword (map (s: s.shortcut) (bravePolicies.SiteSearchSettings or [ ])))
          [
            "arxiv"
            "brave"
            "doi"
            "github"
            "google"
            "maps"
            "nixopt"
            "nixpkgs"
            "pypi"
            "reddit"
            "scholar"
            "scihub"
            "wiki"
            "youtube"
          ];
        # Every keyword is a search address
        assert lib.all (
          s: lib.hasPrefix "https://" s.url && lib.hasInfix "{searchTerms}" s.url
        ) bravePolicies.SiteSearchSettings;
        # The key is generated on the machine: the settings in the Nix store hold only its placeholder
        assert cfg.services.searx.settings.server.secret_key == "$SEARX_SECRET_KEY";
        assert
          (bravePolicies.SpellcheckLanguage or [ ]) == [
            "en-GB"
            "nl"
          ];
        assert user.programs.plasma.configFile.plasma-localerc.Formats.LANG.value == "en_GB.UTF-8";
        # British English with Dutch formats; the desktop is dark and locks with the screen
        assert
          cfg.i18n.defaultLocale == "en_GB.UTF-8"
          && cfg.i18n.extraLocaleSettings.LC_TIME == "en_GB.UTF-8"
          && cfg.i18n.extraLocaleSettings.LC_PAPER == "nl_NL.UTF-8";
        assert
          user.programs.plasma.configFile.plasma-localerc.Formats.LC_TIME.value == "en_GB.UTF-8"
          && user.programs.plasma.configFile.plasma-localerc.Formats.LC_NUMERIC.value == "nl_NL.UTF-8";
        assert
          user.programs.plasma.enable
          && user.programs.plasma.workspace.lookAndFeel == "org.kde.breezedark.desktop";
        # Require private named desktops, their Meta+digit shortcut and one Brave placement rule each
        assert
          user.programs.plasma.kwin.virtualDesktops.names != [ ]
          &&
            builtins.length user.programs.plasma.window-rules
            == builtins.length user.programs.plasma.kwin.virtualDesktops.names;
        # A named Brave window is kept on its desktop, so that naming an existing window moves it
        assert lib.all (rule: rule.apply.desktops.apply == "force") user.programs.plasma.window-rules;
        # Restore Brave when the user opens it, not at login
        # Require the policy, replacement launchers and whole-browser exit before Plasma closes windows
        assert
          (bravePolicies.RestoreOnStartup or null) == 1
          && !(cfg.environment.etc ? "xdg/autostart/brave-session.desktop");
        assert lib.any (package: (package.name or "") == "brave-launchers") cfg.environment.systemPackages;
        assert lib.hasInfix "plasma-shutdown-after-brave"
          user.xdg.dataFile."dbus-1/services/org.kde.Shutdown.service".text;
        assert user.programs.plasma.session.sessionRestore.restoreOpenApplicationsOnLogin == "emptySession";
        # Zotero Connector and Plasma Integration are installed next to Bitwarden
        assert lib.all (id: builtins.elem id (braveDefaults.ExtensionInstallForcelist or [ ])) [
          "ekhagklcjbdpajgpjgmbionohlpdbjgc"
          "cimiefiiaegbelhefglklhhakcgmhkai"
        ];
        assert
          user.programs.plasma.shortcuts.kwin."Switch to Desktop 1" == "Meta+1"
          && user.programs.plasma.shortcuts.kwin."Window to Desktop 1" == "Meta+!";
        assert user.programs.tmux.enable;
        # Require one all-screen panel and exact per-device touchpad and mouse settings
        assert
          builtins.length user.programs.plasma.panels == 1
          && (builtins.head user.programs.plasma.panels).screen == "all";
        assert
          builtins.length user.programs.plasma.input.touchpads == 1
          && (builtins.head user.programs.plasma.input.touchpads).naturalScroll;
        assert (builtins.head user.programs.plasma.input.mice).accelerationProfile != null;
        assert
          user.programs.plasma.kscreenlocker.autoLock
          && user.programs.plasma.kscreenlocker.passwordRequiredDelay == 0;
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
        assert builtins.all (account: !(builtins.elem "docker" account.extraGroups)) (
          builtins.attrValues normalUsers
        );
        assert cfg.services.tailscale.enable && cfg.services.mullvad-vpn.enable;
        # Send the user's GitHub repositories through Bitwarden's SSH key and pinned host keys
        # Keep credentials out of Git files
        assert
          user.programs.git.settings.url."git@github.com:Jeeemieee/".insteadOf
          == "https://github.com/Jeeemieee/";
        assert !(user.programs.git.settings ? credential);
        assert
          lib.hasInfix "IdentityAgent ~/.bitwarden-ssh-agent.sock" user.home.file.".ssh/config".text
          && lib.hasInfix "StrictHostKeyChecking yes" user.home.file.".ssh/config".text;
        # A commit in the two kept repositories goes through the guard, named in the user's own git settings
        assert
          map (include: include.condition) user.programs.git.includes == [
            "gitdir:~/repos/nixos-config/"
            "gitdir:~/repos/nixos-secrets/"
          ];
        assert lib.all (
          include: lib.hasInfix "config-guard-hooks" include.contents.core.hooksPath
        ) user.programs.git.includes;
        # Force Bitwarden's autostart file because its own copy would block later activations
        assert
          user.xdg.configFile."autostart/bitwarden.desktop".force
          && lib.hasInfix "--autostart" user.xdg.configFile."autostart/bitwarden.desktop".text;
        assert cfg.virtualisation.libvirtd.enable;
        # Keep the real backup absent from profile hosts that do not explicitly import it
        assert host.config.networking.hostName == "mimir" || cfg.services.restic.backups == { };
        # Tailscale joins with the host's key, and only after the secrets are installed
        assert cfg.services.tailscale.authKeyFile == cfg.sops.secrets.tailscale_authkey.path;
        assert builtins.elem "sops-install-secrets.service"
          cfg.systemd.services.tailscaled-autoconnect.requires;
        assert builtins.elem "sops-install-secrets.service"
          cfg.systemd.services.tailscaled-autoconnect.after;
        # Match the published eduroam CAT profile, including its method, outer identity, CA and server name
        assert
          wifiProfiles.eduroam.wifi.ssid == "eduroam"
          && wifiProfiles.eduroam.wifi-security.key-mgmt == "wpa-eap";
        assert eduroam.eap == "ttls" && eduroam.phase2-auth == "mschapv2";
        assert eduroam.anonymous-identity == "anonymous@utwente.nl";
        assert eduroam.domain-suffix-match == "radius.utwente.nl";
        assert lib.hasSuffix "utwente-eduroam-ca.pem" eduroam.ca-cert;
        assert eduroam.identity == "$EDUROAM_IDENTITY" && eduroam.password == "$EDUROAM_PASSWORD";
        # Keep network names and passphrases as placeholders filled from the decrypted environment file
        assert
          builtins.attrNames wifiProfiles == [
            "eduroam"
            "gebbeken"
            "home"
            "hotspot"
          ];
        assert builtins.all
          (
            name:
            lib.hasPrefix "$" wifiProfiles.${name}.wifi.ssid
            && lib.hasPrefix "$" wifiProfiles.${name}.wifi-security.psk
          )
          [
            "gebbeken"
            "home"
            "hotspot"
          ];
        assert
          cfg.networking.networkmanager.ensureProfiles.environmentFiles == [ cfg.sops.secrets.wifi_env.path ];
        assert builtins.elem "sops-install-secrets.service"
          cfg.systemd.services.NetworkManager-ensure-profiles.requires;
        assert builtins.elem "sops-install-secrets.service"
          cfg.systemd.services.NetworkManager-ensure-profiles.after;
        # XDG user directories keep their usual names, in lowercase, and are created
        assert userDirs.enable && userDirs.createDirectories;
        assert builtins.all
          (dir: dir == "${user.home.homeDirectory}/${lib.toLower (baseNameOf dir)}" && dir == lib.toLower dir)
          (
            map (name: userDirs.${name}) [
              "desktop"
              "documents"
              "download"
              "music"
              "pictures"
              "projects"
              "publicShare"
              "templates"
              "videos"
            ]
          );
        assert user.xdg.configFile."user-dirs.dirs".text != "";
        # pi is only installed as its sandboxed launcher, never as the bare package
        assert builtins.any (package: (package.name or "") == "pi") user.home.packages;
        assert !(builtins.elem pkgs.pi-coding-agent (cfg.environment.systemPackages ++ user.home.packages));
        # Keep pi's instructions, settings and extension list as forced links into the store
        assert builtins.all (name: (piFile name).force) [
          "AGENTS.md"
          "settings.json"
          "chatgpt-limit.json"
        ];
        assert toString (piFile "AGENTS.md").source == "${inputs.nixos-secrets}/pi/AGENTS.md";
        assert
          builtins.length piSettings.packages == 5
          && builtins.all (lib.hasPrefix "/nix/store/") piSettings.packages;
        assert !(piSettings ? deviceId);
        # Refuse unlisted proprietary packages even if nixpkgs' predicate is accidentally widened
        assert builtins.all (package: builtins.elem (lib.getName package) unfreeAllowed) unfreePackages;
        true;
    in
    {
      ## Part 3. Host policy checks
      # Check the test VM policy and ensure it shares nothing except the host's read-only Nix store
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

      # Check the physical host policy, secret-backed login, encrypted disk, Secure Boot and hardware
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
        assert
          account.initialPassword == null && account.password == null && account.hashedPassword == null;
        assert
          builtins.attrNames mimir.sops.secrets == [
            "restic_env"
            "restic_password"
            "tailscale_authkey"
            "user_password_hash"
            "wifi_env"
          ];
        assert lib.hasSuffix "/secrets/mimir.yaml" mimir.sops.secrets.tailscale_authkey.sopsFile;
        # Back up all of /home hourly without client-side pruning and report failures on the desktop
        assert
          mimir.services.restic.backups.home.paths == [ "/home" ]
          && mimir.services.restic.backups.home.pruneOpts == [ ];
        assert mimir.services.restic.backups.home.passwordFile == mimir.sops.secrets.restic_password.path;
        # Exactly what docs/BACKUP.md lists as left out, whichever module says so
        assert
          lib.sort lib.lessThan mimir.services.restic.backups.home.exclude == [
            ".direnv"
            ".ipynb_checkpoints"
            ".pytest_cache"
            ".venv"
            "/home/*/.cache"
            "/home/*/.local/share/Trash"
            "/home/*/.local/share/docker"
            "/home/*/scratch"
            "__pycache__"
            "node_modules"
          ];
        assert
          mimir.services.restic.backups.home.extraBackupArgs == [
            "--one-file-system"
            "--exclude-caches"
          ];
        assert
          mimir.systemd.services.restic-backups-home.onFailure == [ "restic-backups-home-failed.service" ];
        # Everything but the EFI partition is encrypted: ZFS inside LUKS, swap with a random key
        assert builtins.attrNames mimir.boot.initrd.luks.devices == [ "crypt" ];
        assert
          builtins.attrNames mimir.fileSystems == [
            "/"
            "/boot"
            "/home"
            "/home/jeeemieee/scratch"
            "/home/jeeemieee/scratch/workers"
            "/home/jeeemieee/workers"
            "/nix"
          ];
        # Containers can be given the graphics card
        assert
          mimir.hardware.nvidia-container-toolkit.enable
          && mimir.virtualisation.docker.rootless.daemon.settings.features.cdi;
        # The sizes the user chose for the 2 TB disk
        assert
          mimir.hostSpec.disk.homeReservation == "600G"
          && mimir.hostSpec.disk.nixQuota == "250G"
          && mimir.hostSpec.disk.scratchQuota == "600G"
          && mimir.hostSpec.disk.workersQuota == "200G";
        assert builtins.all (path: mimir.fileSystems.${path}.fsType == "zfs") [
          "/"
          "/nix"
          "/home"
          "/home/jeeemieee/scratch"
        ];
        assert
          mimir.swapDevices != [ ] && builtins.all (swap: swap.randomEncryption.enable) mimir.swapDevices;
        assert !mimir.boot.zfs.forceImportRoot;
        assert mimir.networking.hostId != null;
        # Require lanzaboote with local keys while retaining Microsoft's firmware keys
        assert mimir.boot.lanzaboote.enable && !mimir.boot.loader.systemd-boot.enable;
        assert mimir.boot.lanzaboote.pkiBundle == "/var/lib/sbctl";
        assert mimir.boot.lanzaboote.autoGenerateKeys.enable && mimir.boot.lanzaboote.autoEnrollKeys.enable;
        assert
          mimir.boot.lanzaboote.autoEnrollKeys.includeMicrosoftKeys
          && !mimir.boot.lanzaboote.autoEnrollKeys.allowBrickingMyMachine;
        # Require on-demand NVIDIA, the open kernel module, DisplayLink, Bluetooth and disk monitoring
        assert mimir.hardware.nvidia.open && mimir.hardware.nvidia.prime.offload.enable;
        assert
          mimir.hardware.nvidia.prime.intelBusId == "PCI:0:2:0"
          && mimir.hardware.nvidia.prime.nvidiaBusId == "PCI:1:0:0";
        assert builtins.all (driver: builtins.elem driver mimir.services.xserver.videoDrivers) [
          "nvidia"
          "displaylink"
        ];
        assert mimir.hardware.bluetooth.enable && mimir.services.smartd.enable;
        pkgs.runCommand "mimir-config-check" { } ''
          touch "$out"
        '';

      ## Part 4. Editor binary check
      # Require every native editor extension binary to be x86-64 and loadable from the Nix store
      checks.mimir-vm-editor-binaries =
        let
          user = config.flake.nixosConfigurations.mimir-vm.config.home-manager.users.jeeemieee;
          extensions = user.home.file.".vscode-oss/extensions".source;
        in
        pkgs.runCommand "mimir-vm-editor-binaries-check"
          {
            nativeBuildInputs = [
              pkgs.jq
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

            ## Step 1. Check every ELF file's architecture
            while IFS= read -r -d "" path && IFS= read -r description; do
              case "$description" in
                *"ELF "*"x86-64"*) elfFiles=$((elfFiles + 1)) ;;
                *"ELF "*) elfFiles=$((elfFiles + 1)); echo "FAIL (architecture): $path$description"; failed=1 ;;
              esac
            done < files

            ## Step 2. Require Jupyter's x86-64 glibc ZeroMQ library
            if [ ! -f "$jupyter/dist/node_modules/zeromq/prebuilds/linux-x64/node.napi.glibc.node" ]; then
              echo "FAIL (zeromq): linux-x64 glibc ZeroMQ library is missing"
              failed=1
            fi

            ## Step 3. Check every Node add-on resolves its libraries
            while IFS= read -r path; do
              if ! ldd "$path" > ldd.out 2>&1 || grep -q 'not found' ldd.out; then
                echo "FAIL (ldd): $path"
                cat ldd.out
                failed=1
              fi
            done < node-files

            ## Step 4. Load Jupyter's ZeroMQ binding with Node
            if ! node -e 'require(process.argv[1])' "$jupyter/dist/node_modules/zeromq"; then
              echo "FAIL (require): node cannot load Jupyter's ZeroMQ binding"
              failed=1
            fi

            ## Step 5. Require a colour theme shipped by this VSCodium
            # A renamed theme makes VSCodium try and fail to rewrite the read-only settings
            theme=${
              lib.escapeShellArg user.programs.vscodium.profiles.default.userSettings."workbench.colorTheme"
            }
            themes=$(find ${user.programs.vscodium.package} -path '*/extensions/theme-defaults/package.json' | head -1)
            if ! jq -e --arg theme "$theme" '.contributes.themes | map(.id) | index($theme) != null' "$themes" > /dev/null; then
              echo "FAIL (theme): '$theme' is not a theme of this VSCodium; its themes are: $(jq -r '.contributes.themes | map(.id) | join(", ")' "$themes")"
              failed=1
            fi

            [ "$failed" = 0 ]
            echo "$elfFiles ELF files and $(wc -l < node-files) Node add-ons checked"
            touch "$out"
          '';

      ## Part 5. Network certificate check
      # Match the eduroam root and intermediate certificates published by the CAT profile
      checks.mimir-vm-eduroam-ca =
        pkgs.runCommand "mimir-vm-eduroam-ca-check" { nativeBuildInputs = [ pkgs.openssl ]; }
          ''
            ## Step 1. Split the bundle into one file per certificate
            bundle=${
              config.flake.nixosConfigurations.mimir-vm.config.networking.networkmanager.ensureProfiles.profiles.eduroam."802-1x".ca-cert
            }
            # Ignore comment lines between certificates
            awk '/-----BEGIN CERTIFICATE-----/ { n++; file = "cert-" n } file { print > file } /-----END CERTIFICATE-----/ { file = "" }' "$bundle"
            ## Step 2. Calculate the actual certificate fingerprints
            for cert in cert-*; do
              openssl x509 -in "$cert" -noout -fingerprint -sha256 | cut -d= -f2
            done | sort > actual
            ## Step 3. Compare with the independently published fingerprints
            printf '%s\n' \
              5B:67:8D:C4:40:95:A5:28:95:B6:3B:31:F2:72:27:F4:B3:6C:3E:34:74:91:BF:2B:FA:69:18:37:A5:FB:8C:79 \
              D9:5D:0E:8E:DA:79:52:5B:F9:BE:B1:1B:14:D2:10:0D:32:94:98:5F:0C:62:D9:FA:BD:9C:D9:99:EC:CB:7B:1D \
              | sort > expected
            diff expected actual
            touch "$out"
          '';

      ## Part 6. Full system builds
      # Build both system closures because nix flake check otherwise only evaluates their configurations
      checks.mimir-vm-system = config.flake.nixosConfigurations.mimir-vm.config.system.build.toplevel;
      checks.mimir-system = config.flake.nixosConfigurations.mimir.config.system.build.toplevel;

      ## Part 7. Secret manifest check
      # Validate the enabled test secret and retain coverage of enrolment-only mode
      checks.mimir-vm-secrets =
        let
          vm = config.flake.nixosConfigurations.mimir-vm.config;
          secret = vm.sops.secrets.bootstrap-test;
          # sops-nix expresses root either by name or, by default, as owner/group null with uid/gid 0
          rootOnly =
            s:
            (s.owner == "root" || (s.owner == null && s.uid == 0))
            && (s.group == "root" || (s.group == null && s.gid == 0))
            && s.mode == "0400";
        in
        assert
          builtins.attrNames vm.sops.secrets == [
            "bootstrap-test"
            "tailscale_authkey"
            "wifi_env"
          ];
        # Per-host secrets come from secrets/<hostname>.yaml, shared ones from secrets/shared.yaml
        assert
          lib.hasSuffix "/secrets/mimir-vm.yaml" vm.sops.secrets.tailscale_authkey.sopsFile
          && vm.sops.secrets.tailscale_authkey.key == "tailscale_authkey";
        assert
          lib.hasSuffix "/secrets/shared.yaml" vm.sops.secrets.wifi_env.sopsFile
          && vm.sops.secrets.wifi_env.key == "wifi_env";
        assert rootOnly vm.sops.secrets.tailscale_authkey && rootOnly vm.sops.secrets.wifi_env;
        assert secret.key == "message";
        assert secret.owner == "root" && secret.group == "root";
        assert secret.mode == "0400";
        assert secret.path == "/run/secrets/bootstrap-test";
        assert vm.systemd.services.sops-age-key.requiredBy == [ "sops-install-secrets.service" ];
        assert builtins.elem "sops-install-secrets.service" vm.systemd.services.sops-age-key.before;
        vm.system.build.sops-nix-manifest;
    };
}
