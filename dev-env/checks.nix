# Sandboxed checks of the building blocks (b1-b8, b14, f1-f6); see docs/DEV-ENVIRONMENTS.md
# The uv, CadQuery and GPU tests need the network, a GPU or a missing driver and are run by hand
{
  nixpkgs,
  system,
  devShell,
}:
let
  pkgs = import nixpkgs {
    inherit system;
    config = { };
    overlays = [ ];
  };

  # Run a script in the build environment of a shell: the same inputs and variables,
  # and the shell hook evaluated as at shell entry
  inShell =
    name: blocks: script:
    (devShell { inherit blocks; }).overrideAttrs (old: {
      name = "check-${name}";
      # Open MPI settings that work inside the sandbox
      nativeBuildInputs = old.nativeBuildInputs ++ [ pkgs.mpiCheckPhaseHook ];
      buildPhase = ''
        setupMpiCheck
        eval "$shellHook"
        cp -r ${./tests} tests
        chmod -R u+w tests
        cd tests
        ${script}
        [ -e "$out" ] || touch "$out"
      '';
    });

  # Number of store paths in the closure of a shell whose name matches; exactly one is expected
  oneInClosure =
    name: pattern: blocks:
    pkgs.runCommand "check-${name}"
      {
        closure = pkgs.closureInfo { rootPaths = [ (devShell { inherit blocks; }) ]; };
      }
      ''
        grep -E '^/nix/store/[a-z0-9]+-${pattern}' "$closure/store-paths" | tee matching-paths
        [ "$(wc -l < matching-paths)" -eq 1 ]
        touch "$out"
      '';

  onePetscInClosure = name: oneInClosure name "petsc-[0-9]";

  # True when evaluating the shell fails with a throw
  refused = arguments: !(builtins.tryEval (devShell arguments).drvPath).success;

  cpuTypes = "-vec_type standard -mat_type aij";

  # The release the openfoam block must provide, written here and not read from the
  # package: an update changes dev-env/openfoam.nix and this line
  openfoamRelease = "v2512";

  # OpenFOAM's cavity tutorial (400 cells, icoFoam) as a writable folder
  copyCavity = folder: ''
    cp -r "$FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity" ${folder}
    chmod -R u+w ${folder}
  '';

  # The tutorial decomposes into 9 parts; the checks run on 4 processes
  fourSubdomains = ''
    foamDictionary -entry numberOfSubdomains -set 4 system/decomposeParDict
    foamDictionary -entry coeffs/n -set '(2 2 1)' system/decomposeParDict
  '';

  runParallel = ''
    blockMesh > log.blockMesh
    decomposePar > log.decomposePar
    mpirun -np 4 icoFoam -parallel > log.icoFoam
    grep -q '^nProcs : 4$' log.icoFoam
    grep -q '^End$' log.icoFoam
    reconstructPar > log.reconstructPar
    test -d 0.5
  '';
in
rec {
  b1-mpi4py =
    inShell "b1-mpi4py"
      [
        "python"
        "numerics-cpu"
      ]
      ''
        for ranks in 1 2 4; do
          mpiexec -n $ranks python b1_mpi4py_sum.py
        done
      '';

  b2-petsc4py-mumps =
    inShell "b2-petsc4py-mumps"
      [
        "python"
        "numerics-cpu"
      ]
      ''
        python ksp_tridiag.py --label B2-1rank --n 1000 --solver mumps \
          --expect-vec seq --expect-mat seqaij ${cpuTypes}
        mpiexec -n 2 python ksp_tridiag.py --label B2-2ranks --n 1000 --solver mumps \
          --expect-vec mpi --expect-mat mpiaij ${cpuTypes}
      '';

  b3-slepc4py =
    inShell "b3-slepc4py"
      [
        "python"
        "numerics-cpu"
      ]
      ''
        python g8_slepc.py
      '';

  # Installs the binary and compile_commands.json so that B6 can inspect the binary
  b4-c-petsc =
    inShell "b4-c-petsc"
      [
        "cpp"
        "numerics-cpu"
      ]
      ''
        cmake -G Ninja -S b4 -B build -DCMAKE_BUILD_TYPE=Debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
        cmake --build build
        test -s build/compile_commands.json
        mpiexec -n 2 build/b4_ksp
        mkdir -p "$out/bin"
        cp build/b4_ksp "$out/bin/"
        cp build/compile_commands.json "$out/"
      '';

  b5-fortran-mpi =
    inShell "b5-fortran-mpi"
      [
        "cpp"
        "numerics-cpu"
      ]
      ''
        mpif90 b5_mpi_sum.f90 -o b5_mpi_sum
        mpiexec -n 4 ./b5_mpi_sum | tee b5.out
        grep -q '^ranks: 4 sum of ranks: 6$' b5.out
      '';

  b6-one-petsc-cpu =
    inShell "b6-one-petsc-cpu"
      [
        "python"
        "cpp"
        "numerics-cpu"
      ]
      ''
        storePath() { echo "$1" | cut -d/ -f1-4; }
        linked=$(${b4-c-petsc}/bin/b4_ksp | sed -n 's/^petsc library: //p')
        loaded=$(python b6_petsc_path.py)
        echo "B4 binary links:  $linked"
        echo "petsc4py loads:   $loaded"
        echo "PETSC_DIR:        $PETSC_DIR"
        [ -n "$linked" ] && [ "$(storePath "$linked")" = "$(storePath "$loaded")" ]
        [ "$(storePath "$linked")" = "$PETSC_DIR" ]
      '';

  b6-closure-cpu = onePetscInClosure "b6-closure-cpu" [
    "python"
    "cpp"
    "numerics-cpu"
  ];

  b6-closure-cuda = onePetscInClosure "b6-closure-cuda" [
    "python"
    "cpp"
    "numerics-cuda"
  ];

  b7-variant-cpu = inShell "b7-variant-cpu" [ "numerics-cpu" ] ''
    echo "PETSC_DIR: $PETSC_DIR"
    ! grep '^#define PETSC_HAVE_CUDA ' "$PETSC_DIR/include/petscconf.h"
  '';

  b7-variant-cuda = inShell "b7-variant-cuda" [ "numerics-cuda" ] ''
    echo "PETSC_DIR: $PETSC_DIR"
    grep '^#define PETSC_HAVE_CUDA 1$' "$PETSC_DIR/include/petscconf.h"
  '';

  # Only the refusal itself; the messages are in the recorded evaluation
  b8-refusals =
    assert refused {
      blocks = [
        "numerics-cpu"
        "numerics-cuda"
      ];
    };
    assert refused {
      blocks = [
        "python"
        "julia"
      ];
    };
    pkgs.runCommand "check-b8-refusals" { } ''touch "$out"'';

  b14-ipykernel = inShell "b14-ipykernel" [ "python" ] ''
    python -c "import ipykernel; print('ipykernel', ipykernel.__version__, 'from', ipykernel.__file__)"
  '';

  f1-openfoam-version = inShell "f1-openfoam-version" [ "openfoam" ] ''
    simpleFoam -help | tee f1.out
    grep -q '^Using: OpenFOAM-${openfoamRelease} ' f1.out
  '';

  f2-cavity = inShell "f2-cavity" [ "openfoam" ] ''
    ${copyCavity "cavity"}
    cd cavity
    blockMesh > log.blockMesh
    icoFoam > log.icoFoam
    tail -n 4 log.icoFoam
    grep -q '^End$' log.icoFoam
    test -d 0.5
  '';

  # The tutorial's linear solvers stop at 1e-6 (p) and 1e-5 (U), and DIC works per
  # processor: a parallel run then differs from a serial one in the last digits written
  # Both runs therefore solve to 1e-12, and the fields must agree to the six digits written
  f3-cavity-parallel = inShell "f3-cavity-parallel" [ "openfoam" ] ''
    ${copyCavity "serial"}
    for solver in p pFinal U; do
      foamDictionary -entry solvers/$solver/tolerance -set 1e-12 serial/system/fvSolution
      foamDictionary -entry solvers/$solver/relTol -set 0 serial/system/fvSolution
    done
    cp -r serial parallel
    (
      cd serial
      blockMesh > log.blockMesh
      icoFoam > log.icoFoam
      grep -q '^End$' log.icoFoam
    )
    (
      cd parallel
      ${fourSubdomains}
      ${runParallel}
    )
    for field in U p; do
      awk -v tol=1e-6 -f f3_field_diff.awk serial/0.5/$field parallel/0.5/$field
    done
  '';

  # The hook runs again with a folder for the user's own programs that is writable here, so that
  # FOAM_USER_APPBIN, where wmake installs the program, is on PATH
  # Expected from blockMeshDict: 20 x 20 x 1 cells, 0.1 m x 0.1 m x 0.01 m
  f4-wmake = inShell "f4-wmake" [ "openfoam" ] ''
    export OPENFOAM_USER_DIR="$PWD/user"
    eval "$shellHook"
    [ "$WM_PROJECT_USER_DIR" = "$PWD/user" ]
    (cd f4_wmake && wmake)
    [ "$(command -v f4MeshVolume)" = "$FOAM_USER_APPBIN/f4MeshVolume" ]
    ${copyCavity "cavity"}
    cd cavity
    blockMesh > log.blockMesh
    f4MeshVolume | tee f4.out
    grep -q '^cells: 400$' f4.out
    awk '/^volume: / { error = ($2 - 1e-4) / 1e-4; found = (error <= 1e-12 && error >= -1e-12) } END { exit !found }' f4.out
  '';

  # OpenFOAM and PETSc in one shell: one MPI on PATH and in both libraries, and both run
  f5-openfoam-petsc =
    inShell "f5-openfoam-petsc"
      [
        "python"
        "cpp"
        "numerics-cpu"
        "openfoam"
      ]
      ''
        storePath() { echo "$1" | cut -d/ -f1-4; }
        launchers=$(for name in mpirun mpiexec; do type -a -p $name; done | xargs -n 1 realpath | sort -u)
        echo "MPI launchers on PATH:"
        echo "$launchers"
        [ "$(echo "$launchers" | wc -l)" -eq 1 ]
        pstreamMpi=$(ldd "$FOAM_LIBBIN/$FOAM_MPI/libPstream.so" | awk '/libmpi\.so/ { print $3 }')
        petscMpi=$(ldd "$PETSC_DIR/lib/libpetsc.so" | awk '/libmpi\.so/ { print $3 }')
        echo "OpenFOAM links: $pstreamMpi"
        echo "PETSc links:    $petscMpi"
        [ -n "$pstreamMpi" ] && [ "$pstreamMpi" = "$petscMpi" ]
        [ "$(storePath "$pstreamMpi")" = "$(storePath "$launchers")" ]

        ${copyCavity "cavity"}
        (
          cd cavity
          ${fourSubdomains}
          ${runParallel}
        )

        cmake -G Ninja -S b4 -B build
        cmake --build build
        mpiexec -n 2 build/b4_ksp
        mpiexec -n 2 python ksp_tridiag.py --label F5-2ranks --n 1000 --solver mumps \
          --expect-vec mpi --expect-mat mpiaij ${cpuTypes}
      '';

  # Where the user's own solvers and libraries go: that folder is first on PATH and on LD_LIBRARY_PATH
  # In the user's own terminal it is a hidden folder of the home, which pi never shares; in a pi
  # sandbox, whose home is in memory, it is inside the project; a named folder wins over both
  f6-user-folder = inShell "f6-user-folder" [ "openfoam" ] ''
    mkdir -p project/case home
    echo "{ }" > project/flake.nix
    unset OPENFOAM_USER_DIR
    userFolder() { (export HOME=$1; cd project/case && eval "$shellHook" && echo "$WM_PROJECT_USER_DIR|$FOAM_USER_APPBIN|$FOAM_USER_LIBBIN"); }
    expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; exit 1; fi; }

    # A home on a disk, as in the user's own terminal
    [ "$(stat -f -c %T "$PWD/home")" != tmpfs ]
    own=$(userFolder "$PWD/home")
    expect "in a terminal" "''${own%%|*}" "$PWD/home/.local/share/openfoam/${openfoamRelease}"
    case "$own" in *"$PWD/project"*) echo "FAIL: a folder of the project is searched in a terminal: $own"; exit 1 ;; esac

    # A home in memory, as in a pi sandbox: the project, found from a folder below it
    sandboxHome=$(mktemp -d /dev/shm/home.XXXXXX)
    [ "$(stat -f -c %T "$sandboxHome")" = tmpfs ]
    inside=$(userFolder "$sandboxHome")
    expect "in a sandbox" "''${inside%%|*}" "$PWD/project/.openfoam"
    rmdir "$sandboxHome"

    # Programs and libraries are searched in that folder, and it comes first
    expect "the programs' folder" "$(echo "$own" | cut -d'|' -f2)" "$PWD/home/.local/share/openfoam/${openfoamRelease}/platforms/$WM_OPTIONS/bin"
    (export HOME=$PWD/home; cd project/case && eval "$shellHook" && [ "''${PATH%%:*}" = "$FOAM_USER_APPBIN" ] && [ "''${LD_LIBRARY_PATH%%:*}" = "$FOAM_USER_LIBBIN" ]) \
      || { echo "FAIL: the user's folder is not first on PATH and LD_LIBRARY_PATH"; exit 1; }

    # A named folder wins
    expect "a named folder" "$(export OPENFOAM_USER_DIR=$PWD/named; userFolder "$PWD/home" | cut -d'|' -f1)" "$PWD/named"
  '';

  f5-closure = oneInClosure "f5-closure" "openmpi-[0-9.]+$" [
    "python"
    "cpp"
    "numerics-cpu"
    "openfoam"
  ];
}
