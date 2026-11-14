{
  inputs,
  lib,
  config,
  withSystem,
  ...
}:
let
  prefix = "host-";
  # Every flake.modules.nixos.host-<name> becomes nixosConfigurations.<name>
  hostModules = lib.filterAttrs (name: _: lib.hasPrefix prefix name) config.flake.modules.nixos;
in
{
  flake.nixosConfigurations = lib.mapAttrs' (
    name: module:
    {
      name = lib.removePrefix prefix name;
      value = withSystem "x86_64-linux" ({ pkgs, ... }:
        inputs.nixpkgs.lib.nixosSystem {
          modules = [
            module
            inputs.home-manager.nixosModules.home-manager
            { nixpkgs.pkgs = pkgs; }
            {
              # Use the system package set and install user packages through the system closure
              # instead of imperatively into each user's mutable nix profile
              home-manager = {
                useGlobalPkgs = true;
                useUserPackages = true;
              };

              # Home Manager does not load its session variables unless it manages the shell, so every login shell sources them here
              environment.extraInit = ''
                if [ -f "/etc/profiles/per-user/$USER/etc/profile.d/hm-session-vars.sh" ]; then
                  . "/etc/profiles/per-user/$USER/etc/profile.d/hm-session-vars.sh"
                fi
              '';
            }
          ];
        }
      );
    }
  ) hostModules;
}
