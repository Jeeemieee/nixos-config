# Development shells composed from building blocks
#
#   devShell = import ./dev-shell.nix { inherit nixpkgs system; };
#   devShell { blocks = [ "python" "numerics-cpu" ]; packages = pkgs: [ pkgs.gmsh ]; }
#
# Blocks: python, cpp, openfoam, and at most one of numerics-cpu, numerics-cuda
{ nixpkgs, system }:
let
  lib = import "${nixpkgs}/lib";
  cuda = import ./cuda-overlay.nix;

  knownBlocks = [
    "python"
    "cpp"
    "numerics-cpu"
    "numerics-cuda"
    "openfoam"
  ];

  # Unmodified nixpkgs for every shell without numerics-cuda; explicit empty config and
  # overlays so that nothing from the user's ~/.config/nixpkgs leaks in
  plainPkgs = import nixpkgs {
    inherit system;
    config = { };
    overlays = [ ];
  };

  # Separate instance for shells with numerics-cuda: the overlay replaces PETSc and
  # SLEPc only, every other package evaluates to the same store path as in plainPkgs
  cudaPkgs = import nixpkgs {
    inherit system;
    overlays = [ cuda.overlay ];
    config.allowUnfreePredicate = pkg: builtins.elem (lib.getName pkg) cuda.unfreeNames;
  };
in
{
  blocks ? [ ],
  packages ? (pkgs: [ ]),
}:
let
  has = block: builtins.elem block blocks;
  unknownBlocks = lib.subtractLists knownBlocks blocks;
  hasNumerics = has "numerics-cpu" || has "numerics-cuda";
  pkgs = if has "numerics-cuda" then cudaPkgs else plainPkgs;

  # One PETSc and one SLEPc per shell: the builds that carry petsc4py and slepc4py are
  # also the ones C, C++ and Fortran use (PETSC_DIR, SLEPC_DIR, pkg-config)
  petsc = pkgs.python313Packages.petsc4py;
  slepc = pkgs.python313Packages.slepc4py;

  # OpenFOAM from ESI, built against pkgs.mpi, the MPI of the numerics blocks
  openfoam = import ./openfoam.nix { inherit pkgs; };

  # Libraries that PyPI wheels expect from the system
  wheelLibraries = [
    pkgs.stdenv.cc.cc.lib # libstdc++, libgcc_s: nearly every compiled wheel (numpy, matplotlib)
    pkgs.zlib # libz: baseline, not needed by any wheel tested so far
    pkgs.libGL # libGL: cadquery-ocp
    pkgs.libx11 # libX11: cadquery-ocp
    pkgs.expat # libexpat: cadquery-ocp
  ];

  # The library path is set by the wrapper of the Python executable, not in the shell,
  # so that it only reaches Python processes
  pythonEnv =
    (pkgs.python313.withPackages (
      ps:
      [ ps.ipykernel ]
      ++ lib.optionals hasNumerics [
        ps.numpy
        ps.scipy
        ps.mpi4py
        ps.petsc4py
        ps.slepc4py
      ]
    )).override
      {
        makeWrapperArgs = [
          "--prefix"
          "LD_LIBRARY_PATH"
          ":"
          (lib.makeLibraryPath wheelLibraries)
        ];
      };

  # nixpkgs' Python setup hook fills PYTHONPATH in shells with numerics (PETSc
  # propagates numpy and with it the bare Python). It would put every Nix package
  # before the project's .venv and leak into Pythons outside the shell; the wrapped
  # Python finds its packages without it
  commonShellHook = ''
    unset PYTHONPATH
  '';

  # PETSc aborts when it initialises the CUDA device with an MPI that is not GPU-aware
  # (nixpkgs' Open MPI); prepended so that a later user option still wins
  # No stub fallback: without the driver PETSc cannot be loaded, say so once
  cudaShellHook = ''
    export PETSC_OPTIONS="-use_gpu_aware_mpi 0''${PETSC_OPTIONS:+ $PETSC_OPTIONS}"
    if ! ( IFS=:; for dir in /run/opengl-driver/lib $LD_LIBRARY_PATH; do [ -e "$dir/libcuda.so.1" ] && exit 0; done; exit 1 ); then
      echo "numerics-cuda: libcuda.so.1 is neither in /run/opengl-driver/lib nor on LD_LIBRARY_PATH; PETSc cannot be loaded without the NVIDIA driver" >&2
    fi
  '';

  # OpenFOAM's own environment script, as on any other system: it puts the programs
  # and wmake on PATH, the libraries on LD_LIBRARY_PATH (OpenFOAM loads its libraries
  # by name, also the user's own from FOAM_USER_LIBBIN) and sets WM_* and FOAM_*
  #
  # Where wmake installs the user's own solvers and libraries (WM_PROJECT_USER_DIR). That folder comes
  # first on PATH and on LD_LIBRARY_PATH for every program of the shell, so it must not be a folder that
  # an agent can write and the user's own terminal then searches:
  #   - OPENFOAM_USER_DIR, if it is set
  #   - inside a pi sandbox, whose home folder is in memory: .openfoam in the project (the nearest folder
  #     upwards with a flake.nix), which only the agent's own shells use
  #   - otherwise ~/.local/share/openfoam/v<release>, shared by the user's projects wherever their cases lie.
  #     pi never shares a hidden folder of the home, so no agent can write it. The solvers' sources are
  #     developed elsewhere; the user runs wmake himself to build his copy
  #
  # Where errors end the shell (set -e, as in the checks) the script would stop half-way:
  # one of its helpers returns 1 in its normal course. `|| true` switches that off for
  # the script, and the test after it says whether OpenFOAM is loaded
  openfoamShellHook = ''
    if [ -n "''${OPENFOAM_USER_DIR:-}" ]; then
      openfoamUserDir=$OPENFOAM_USER_DIR
    elif [ "$(stat -f -c %T "''${HOME:-/}" 2> /dev/null)" = tmpfs ]; then
      openfoamUserDir=$PWD
      while [ "$openfoamUserDir" != / ] && [ ! -e "$openfoamUserDir/flake.nix" ]; do openfoamUserDir=$(dirname "$openfoamUserDir"); done
      if [ "$openfoamUserDir" = / ]; then openfoamUserDir=$PWD; fi
      openfoamUserDir=$openfoamUserDir/.openfoam
    else
      openfoamUserDir=$HOME/.local/share/openfoam/v${openfoam.version}
    fi
    source ${openfoam}/opt/OpenFOAM-${openfoam.version}/etc/bashrc WM_PROJECT_USER_DIR="$openfoamUserDir" || true
    unset openfoamUserDir
    if [ "''${WM_PROJECT_DIR:-}" != "${openfoam}/opt/OpenFOAM-${openfoam.version}" ]; then
      echo "openfoam: etc/bashrc of ${openfoam} did not set WM_PROJECT_DIR; OpenFOAM is not loaded" >&2
    fi
  '';
in
if (unknownBlocks != [ ]) then
  throw "devShell: unknown block(s) ${lib.concatStringsSep ", " unknownBlocks}; known blocks are ${lib.concatStringsSep ", " knownBlocks}"
else if (has "numerics-cpu" && has "numerics-cuda") then
  throw "devShell: the blocks numerics-cpu and numerics-cuda exclude each other; choose at most one"
else
  pkgs.mkShell (
    {
      packages =
        # First on PATH: the Python environment also carries mpiexec (through mpi4py),
        # wrapped with the Python-scoped library path; MPI programs must not get that
        lib.optional (hasNumerics || has "openfoam") pkgs.mpi
        ++ lib.optionals (has "python") [
          pythonEnv
          pkgs.uv
        ]
        # The C and C++ compilers come with mkShell's stdenv
        ++ lib.optionals (has "cpp") [
          pkgs.gfortran
          pkgs.cmake
          pkgs.ninja
          pkgs.pkg-config
          pkgs.clang-tools
          pkgs.gdb
        ]
        # What wmake needs besides the compilers of mkShell's stdenv
        ++ lib.optionals (has "openfoam") [
          pkgs.flex
          pkgs.gnum4
        ]
        ++ packages pkgs;

      buildInputs =
        lib.optionals hasNumerics [
          petsc
          slepc
        ]
        # nvcc and the CUDA headers and libraries for the project's own CUDA code
        ++ lib.optional (has "numerics-cuda") pkgs.petscCudaToolkit;

      shellHook =
        commonShellHook
        + lib.optionalString (has "numerics-cuda") cudaShellHook
        + lib.optionalString (has "openfoam") openfoamShellHook;
    }
    // lib.optionalAttrs (has "python") {
      # uv uses the Nix Python and never downloads one
      UV_PYTHON = "${pythonEnv}/bin/python";
      UV_PYTHON_DOWNLOADS = "never";
    }
    // lib.optionalAttrs (has "cpp") {
      # _FORTIFY_SOURCE needs optimisation; without this, CMake Debug builds get -O2
      hardeningDisable = [ "fortify" ];
    }
  )
