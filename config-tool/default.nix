# The config command package
#
# What it is    The upkeep command described in docs/UPKEEP.md, assembled from config.sh and its dependencies
# Who uses it   Workstations and the admin shell through packages.config and modules.homeManager.config-tool
# A caller adds A package set, and tests may replace the real check and build commands with stand-ins
# Protected     Yes: this command guards checks, builds, commits and protected files (docs/UPKEEP.md)
pkgs:
{
  checkCommand ? "",
  buildCommand ? "",
}:
let
  ## Part 1. Files embedded in the command
  # Keep the protection policy in one list shared by the command and the pi launcher
  protected = pkgs.writeText "config-protected.json" (builtins.toJSON (import ./protected.nix));

  # Refuse Python mistakes while the system builds, like shellcheck does for the shell scripts
  updateExtensions =
    pkgs.runCommand "update-extensions.py" { nativeBuildInputs = [ pkgs.python3Packages.pyflakes ]; }
      ''
        pyflakes ${./update-extensions.py}
        cp ${./update-extensions.py} "$out"
      '';
in
pkgs.writeShellApplication {
  ## Part 2. Command package
  # Install the command under the short name used throughout docs/UPKEEP.md
  name = "config";

  # Give config.sh every program it calls without relying on the user's PATH
  runtimeInputs = [
    pkgs.git
    pkgs.jq
    pkgs.sops
    pkgs.yq-go
    pkgs.findutils
    pkgs.coreutils
    pkgs.gnugrep
    pkgs.hostname
  ];

  # Tests replace the empty command overrides with stand-ins for checks, nix and nixos-rebuild
  text = ''
    PROTECTED=${protected}
    CHECK_COMMAND=${pkgs.lib.escapeShellArg checkCommand}
    BUILD_COMMAND=${pkgs.lib.escapeShellArg buildCommand}
    UPDATE_EXTENSIONS() { ${pkgs.python3}/bin/python3 -I ${updateExtensions} "$@"; }
  ''
  + builtins.readFile ./config.sh;
}
