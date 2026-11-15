# The workers' live overview, its check
#
# What it is    Both builds of workers-watch, and the tests T2 to T8, R2 and V1 to V6 against them (tests/run.py)
# Who uses it   modules/dev/workers.nix, as the check workers-watch
# A caller adds A package set
# Protected     Yes: it is the test of a program the user runs on what agents wrote (docs/UPKEEP.md)
pkgs:
let
  build = import ./package.nix pkgs;
  normal = build { };
  sanitized = build { sanitize = true; };
  # Only the test of the status command builds this, with a stand-in for `workers status --json` that the test controls
  commanded = build {
    statusCommand = [
      "${pkgs.runtimeShell}"
      "${./tests/stand-in.sh}"
      "${./samples/normal.json}"
    ];
  };
  # What the tests read besides the programs
  tests = pkgs.lib.fileset.toSource {
    root = ./.;
    fileset = pkgs.lib.fileset.unions [
      ./CMakeLists.txt
      ./src
      ./samples
      ./tests
      ./tools
    ];
  };
in
{
  workers-watch =
    pkgs.runCommand "workers-watch-check"
      {
        nativeBuildInputs = [
          pkgs.python3
          pkgs.python3Packages.pyflakes
          # T7 reads the list of imported functions with nm
          pkgs.binutils
        ];
      }
      ''
        failed=0
        expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; failed=1; fi; }

        ## Step 1. T1: both builds exist, so they compiled with warnings as errors; the scripts have no unused names
        expect "T1 the normal build runs" "$(${normal}/bin/workers-watch --help | head -n 1)" "workers-watch: the live overview of the workers. It only displays."
        expect "T1 the sanitized build runs" "$(${sanitized}/bin/workers-watch --help | head -n 1)" "workers-watch: the live overview of the workers. It only displays."
        pyflakes ${tests}/tests/run.py ${tests}/tests/measure.py ${tests}/tools/generate.py

        ## Step 2. The sample in the repository is what the generator writes: it has not drifted from it
        expect "the sample is the generator's" "$(python3 ${tests}/tools/generate.py --stdout | cmp -s - ${tests}/samples/normal.json && echo same || echo different)" same

        ## Step 3. T2 to T8, R2 and V1 to V6; the tests need the sources beside them, for the search of T7
        cp -r ${tests} work && chmod -R u+w work
        python3 work/tests/run.py --normal ${normal}/bin/workers-watch --sanitized ${sanitized}/bin/workers-watch \
          --commanded ${commanded}/bin/workers-watch | tee results.txt || failed=1
        expect "the tests ended with" "$(tail -n 1 results.txt)" "all passed"

        [ "$failed" = 0 ] || exit 1
        mkdir -p "$out" && cp results.txt "$out/"
      '';
}
