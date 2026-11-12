# Sandboxed checks of the building blocks (b1-b8, b14); see docs/DEV-ENVIRONMENTS.md
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

  # Number of PETSc store paths in the closure of a shell; exactly one is expected
  onePetscInClosure =
    name: blocks:
    pkgs.runCommand "check-${name}"
      {
        closure = pkgs.closureInfo { rootPaths = [ (devShell { inherit blocks; }) ]; };
      }
      ''
        grep -E '^/nix/store/[a-z0-9]+-petsc-[0-9]' "$closure/store-paths" | tee petsc-paths
        [ "$(wc -l < petsc-paths)" -eq 1 ]
        touch "$out"
      '';

  # True when evaluating the shell fails with a throw
  refused = arguments: !(builtins.tryEval (devShell arguments).drvPath).success;

  cpuTypes = "-vec_type standard -mat_type aij";
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
}
