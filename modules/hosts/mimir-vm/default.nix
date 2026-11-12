{ inputs, ... }@topLevel:
{
  flake.modules.nixos.host-mimir-vm =
    { config, lib, pkgs, ... }:
    {
      imports = [
        "${inputs.nixpkgs}/nixos/modules/virtualisation/qemu-vm.nix"
        topLevel.config.flake.modules.nixos.workstation
        topLevel.config.flake.modules.nixos.secrets-test
      ];

      # A test VM, removed once the laptop has migrated; everything shared with the laptop is in nixos.workstation
      # The existing VM disk's public recipient is in the pinned ciphertext
      hostSpec.hasSecrets = true;
      networking.hostName = "mimir-vm";

      # Public trial password only: change it with passwd after the first login
      users.mutableUsers = true;
      users.users.jeeemieee.initialPassword = "mimir";

      home-manager.users.jeeemieee = {
        home.stateVersion = "25.11";

        # Apply the declared VM mode after Plasma has restored any saved display state
        systemd.user.services.mimir-vm-display = {
          Unit = {
            Description = "Apply the declared Mimir VM display mode";
            After = [ "plasma-plasmashell.service" ];
            PartOf = [ "graphical-session.target" ];
          };
          Service = {
            Type = "oneshot";
            RemainAfterExit = true;
            TimeoutStartSec = 30;
            ExecStart = "${pkgs.kdePackages.libkscreen}/bin/kscreen-doctor output.Virtual-1.mode.${toString config.virtualisation.resolution.x}x${toString config.virtualisation.resolution.y}@60 output.Virtual-1.scale.1";
          };
          Install.WantedBy = [ "plasma-workspace.target" ];
        };
      };
      system.stateVersion = "25.11";

      virtualisation = {
        memorySize = 8192;
        cores = 4;
        diskSize = 24576;
        graphics = true;
        # Full HD, matching the external monitors and the chosen 16:9 aspect ratio
        resolution = { x = 1920; y = 1080; };

        # Persist guest-installed store paths on its disk, not an ephemeral tmpfs
        writableStoreUseTmpfs = false;
        fileSystems."/nix/.ro-store".options = [ "ro" ];

        # The standard launcher shares the host store, but no home or exchange folders
        sharedDirectories = lib.mkForce {
          nix-store = {
            source = "/nix/store";
            target = "/nix/.ro-store";
            securityModel = "none";
          };
        };
        forwardPorts = [ ];
        qemu.options = [
          "-vga none"
          "-device virtio-vga,xres=${toString config.virtualisation.resolution.x},yres=${toString config.virtualisation.resolution.y}"
          "-display gtk,gl=off"
        ];
      };
    };
}
