# Host configuration assembly
#
# What it is    The rule that turns every host-<name> module into a NixOS machine
# Who uses it   The flake automatically for each module published under flake.modules.nixos
# A host adds   One host-<name> module with its imports, hardware and state versions
# Protected     Yes: this decides what every host contains and what every login shell runs (docs/UPKEEP.md)
{
  inputs,
  lib,
  config,
  withSystem,
  ...
}:
let
  # Keep the naming convention in one value used for selection and removal
  prefix = "host-";

  # Select only host modules so ordinary reusable modules do not become machines
  hostModules = lib.filterAttrs (name: _: lib.hasPrefix prefix name) config.flake.modules.nixos;
in
{
  # Turn each selected host module into the public nixosConfigurations.<name> output
  flake.nixosConfigurations = lib.mapAttrs' (name: module: {
    name = lib.removePrefix prefix name;
    value = withSystem "x86_64-linux" (
      { pkgs, ... }:
      inputs.nixpkgs.lib.nixosSystem {
        modules = [
          # Start with the host's own composition
          module

          # Add Home Manager to the same NixOS evaluation
          inputs.home-manager.nixosModules.home-manager

          # Use the package set already chosen for this system
          { nixpkgs.pkgs = pkgs; }
          {
            # Use the system package set and put user packages in the system closure
            # This avoids separate mutable user profiles
            home-manager = {
              useGlobalPkgs = true;
              useUserPackages = true;
            };

            # Load Home Manager's session variables even though it does not manage the shell itself
            environment.extraInit = ''
              if [ -f "/etc/profiles/per-user/$USER/etc/profile.d/hm-session-vars.sh" ]; then
                . "/etc/profiles/per-user/$USER/etc/profile.d/hm-session-vars.sh"
              fi
            '';
          }
        ];
      }
    );
  }) hostModules;
}
