# Builds the config command (config.sh) for a package set; see docs/UPKEEP.md
# checkCommand: only the test of the command sets it, to a stand-in for the real checks
pkgs:
{
  checkCommand ? "",
}:
let
  protected = pkgs.writeText "config-protected.json" (builtins.toJSON (import ./protected.nix));
  # Checked for unused names and syntax when the system is built, as the shell scripts are by shellcheck
  updateExtensions =
    pkgs.runCommand "update-extensions.py" { nativeBuildInputs = [ pkgs.python3Packages.pyflakes ]; }
      ''
        pyflakes ${./update-extensions.py}
        cp ${./update-extensions.py} "$out"
      '';
in
pkgs.writeShellApplication {
  name = "config";
  runtimeInputs = [
    pkgs.git
    pkgs.jq
    pkgs.sops
    pkgs.coreutils
    pkgs.gnugrep
  ];
  text = ''
    PROTECTED=${protected}
    CHECK_COMMAND=${pkgs.lib.escapeShellArg checkCommand}
    UPDATE_EXTENSIONS() { ${pkgs.python3}/bin/python3 -I ${updateExtensions} "$@"; }
  ''
  + builtins.readFile ./config.sh;
}
