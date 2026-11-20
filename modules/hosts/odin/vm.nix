# Test composition for Odin without production hardware or recipients
{ config, inputs, ... }:
let
  inherit (config.flake) modules;
in
{
  flake.modules.nixos.odin-vm-test = {
    imports = [
      inputs.home-manager.nixosModules.home-manager
      modules.nixos.odin-facts
      modules.nixos.workstation
      modules.nixos.gaming
      modules.nixos.login-password
      modules.nixos.backup
      modules.nixos.tailscale-ssh-server
    ];

    networking.hostName = "odin-vm-test";
    home-manager = {
      useGlobalPkgs = true;
      useUserPackages = true;
    };
    home-manager.users.jeeemieee.home.stateVersion = "26.05";
    system.stateVersion = "26.05";
  };
}
