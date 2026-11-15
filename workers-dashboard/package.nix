# The workers' live overview, as a package
#
# What it is    workers-watch: a terminal program that shows what `workers status --json` reports; it only displays
# Who uses it   modules/dev/workers.nix, for `workers watch` and for the two checks that run its reader; checks.nix beside it
# A caller adds A package set; sanitize for the tests' build with the address and undefined-behaviour sanitizers;
#               statusCommand, the command whose output is the status document, as a list that starts with an absolute path
#               Without statusCommand the program needs --file
# Protected     Yes: the user runs this program on what agents wrote (docs/UPKEEP.md)
pkgs:
{
  sanitize ? false,
  statusCommand ? [ ],
}:
pkgs.stdenv.mkDerivation {
  pname = "workers-watch" + pkgs.lib.optionalString sanitize "-sanitized";
  version = "0.1";

  # Only what the build reads, so that a change to the tests or the report does not rebuild it
  src = pkgs.lib.fileset.toSource {
    root = ./.;
    fileset = pkgs.lib.fileset.unions [
      ./CMakeLists.txt
      ./src
    ];
  };

  nativeBuildInputs = [
    pkgs.cmake
    pkgs.ninja
  ];
  buildInputs = [
    pkgs.ftxui
    pkgs.nlohmann_json
  ];

  cmakeFlags = [
    (pkgs.lib.cmakeBool "SANITIZE" sanitize)
    (pkgs.lib.cmakeFeature "STATUS_COMMAND" (builtins.concatStringsSep ";" statusCommand))
  ];

  # The sanitizers replace what fortify checks and do not work together with it
  hardeningDisable = pkgs.lib.optionals sanitize [
    "fortify"
    "fortify3"
  ];
  # Keep the names in the sanitizers' reports
  dontStrip = sanitize;

  meta.mainProgram = "workers-watch";
}
