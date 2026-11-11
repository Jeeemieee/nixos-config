# Per-host settings read by shared modules; every host gets this module from modules/flake/host-machines.nix
{
  flake.modules.nixos.hostSpec =
    { lib, ... }:
    {
      options.hostSpec.hasSecrets = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Whether this host's age recipient is enrolled in the pinned encrypted secrets, so that its
          configured secrets are enabled. Leave false to generate the host's age key and enrol it first.
        '';
      };
    };
}
