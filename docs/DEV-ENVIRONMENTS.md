# Development environments

A project gets its tools from building blocks that are defined once, in `dev-env/`, and referenced by every project. The environment is active only inside the project folder (direnv), nothing is installed system-wide, and projects on the same revision of this repository share one build of every tool.

## Blocks

| Block | Contents |
| --- | --- |
| `python` | Python 3.13, `uv`, `ipykernel`; PyPI wheels find libstdc++, zlib, libGL, libX11 and expat through a library path that only Python processes get |
| `cpp` | C and C++ compilers, `gfortran`, CMake, Ninja, pkg-config, clangd (`clang-tools`), gdb; without the `fortify` hardening, so CMake Debug builds are not optimised |
| `numerics-cpu` | Open MPI, PETSc 3.25 and SLEPc with MUMPS, ScaLAPACK, METIS and hypre, unmodified from nixpkgs (binary cache); with `python` also numpy, scipy, mpi4py, petsc4py and slepc4py |
| `numerics-cuda` | The same with PETSc and SLEPc built for CUDA 12.6 (GPU architecture 8.9, the laptop's RTX 3500 Ada), plus `nvcc` and the CUDA libraries for the project's own code |
| `openfoam` | OpenFOAM v2512 from ESI (openfoam.com) with Scotch, CGAL and FFTW, built against the same Open MPI as the numerics blocks; its environment loaded as by `source etc/bashrc`; `wmake` with `flex` and `m4` for the project's own solvers and libraries. Without ParaView, and without the modules that are separate repositories (cfMesh, the PETSc solver interface, ADIOS, the ParaView plugins) |

A project chooses any of `python`, `cpp` and `openfoam`, and at most one numerics block. Both numerics blocks together, or an unknown name, fail with a message. Extra tools go into `packages`.

The blocks are a flake of their own, `dev-env/flake.nix`, whose only input is `nixpkgs` (`nixos-unstable`), independent of the hosts' package set. A project's lock therefore holds only `blocks` and that `nixpkgs`, not this repository's other inputs. This repository's `nixpkgs-unstable` follows the blocks' pin, so the `dev-env-*` checks test exactly what projects get; its lock keeps a copy of that pin, and the `dev-env-lock-in-step` check fails when the copy and `dev-env/flake.lock` differ. `lib.pkgs` is the blocks' package set, for a project that builds a package of its own with the shell's Python. The CUDA packages are unfree; their names are allowed inside `dev-env/cuda-overlay.nix` only, not on the hosts' allowlist. The first use of `numerics-cuda` on a machine builds PETSc with CUDA (about a quarter of an hour).

The `openfoam` block takes OpenFOAM as nixpkgs packages it, v2512, which the binary cache serves: nothing is compiled, and it takes 2.5 GiB in the Nix store. A newer release than nixpkgs has can be had by giving `dev-env/openfoam.nix` the release's version and source; it is then compiled on the machine, about 65 minutes on 8 cores for v2606 (measured 2026-11-14), at the first use and again after most updates of `nixpkgs-unstable`. The release the checks expect is written in `dev-env/checks.nix`. ParaView is a program of the desktop ([APPS.md](APPS.md)), not part of the block, and `paraFoam` is not provided.

## Start a project

```bash
mkdir ~/projects/<name> && cd ~/projects/<name> && git init
nix flake init -t "github:Jeeemieee/nixos-config?dir=dev-env#project"
```

The template keeps the environment in `environment/`: `environment/nix/` holds only `flake.nix` and `flake.lock`, and `.envrc` enters it as a path flake of that folder (`use flake "path:$PWD/environment/nix"`). Entering the shell then copies those two files into the Nix store, not the project; a flake at the top of a Git repository copies every tracked file at every evaluation (58 MiB for `pyVarVal`). What tools look for at the top stays there: `pyproject.toml`, `setup.py`, `uv.lock`, `.envrc`, `AGENTS.md`, `workers.toml`, `.gitignore`, `README.md`.

A project's flake names the blocks as `inputs.blocks.url = "github:Jeeemieee/nixos-config?dir=dev-env";`. The old address without `?dir=dev-env` still works, but its lock carries every input of this repository.

Choose the blocks in `environment/nix/flake.nix`, then `direnv allow` and `nix-direnv-reload`; run `nix-direnv-reload` again after every change of `flake.nix` or `flake.lock`, since the environment is not reloaded by itself (see [MIMIR-VM.md](MIMIR-VM.md), direnv). The template's `README.md` describes the Python steps: `uv venv --system-site-packages` once, then `uv add <package>`; the numerics packages come from the shell and are listed under `exclude-dependencies` in `pyproject.toml`, so uv does not install its own copies.

Update the blocks of a project with `nix flake update blocks`, then delete `.venv` and create it again.

## What a shell sets

- `PYTHONPATH` is unset: nixpkgs would fill it with the shell's packages, which would then override the project's `.venv`
- Open MPI is first on `PATH`, before the Python environment's own `mpiexec`, which carries Python's library path
- `PETSC_DIR` and `SLEPC_DIR` point at the builds that petsc4py and slepc4py use: one PETSc and one SLEPc per shell, also for C, C++ and Fortran (pkg-config)
- `UV_PYTHON` is the shell's Python and `UV_PYTHON_DOWNLOADS=never`: uv never downloads a Python
- `openfoam`: OpenFOAM's own `etc/bashrc` is sourced. It puts the programs and `wmake` on `PATH`, sets `WM_*` and `FOAM_*`, and puts OpenFOAM's libraries and those of Scotch, FFTW, Boost and Open MPI on `LD_LIBRARY_PATH`, which every program started from the shell sees. OpenFOAM needs that: it loads libraries by name, also the project's own. OpenFOAM itself is read-only in the Nix store. `wmake` installs your own solvers and libraries into OpenFOAM's user folder (`FOAM_USER_APPBIN`, `FOAM_USER_LIBBIN`), which comes first on both paths for every program of the shell. It must therefore never be a folder that an agent can write and your own terminal then searches, so the block chooses it:
  - in your own terminal: `~/.local/share/openfoam/v2512/`, shared by all your projects, wherever their cases lie. pi never shares a hidden folder of the home, so no agent can write it;
  - inside a pi sandbox (recognised by its home folder in memory): `.openfoam/` in the project, the nearest folder upwards with a `flake.nix`, or else the folder the shell was entered from (with the `environment/nix` layout and direnv, the project's top folder). The agent compiles and tests there; add `.openfoam/` to the project's `.gitignore`, as the template does;
  - `OPENFOAM_USER_DIR`, if you set it, wins over both.

  The sources of your solvers live wherever you develop them. After an agent wrote or changed one, run `wmake` in it yourself: that builds your copy, and is the moment to look at what changed. direnv carries variables only: the aliases of an OpenFOAM shell (`run`, `tut`, `src`, `wmSet`) exist in `nix develop`, not under direnv; use `cd "$FOAM_RUN"` and the like
- `numerics-cuda`: `-use_gpu_aware_mpi 0` is prepended to `PETSC_OPTIONS`, because nixpkgs' Open MPI is not GPU-aware and PETSc otherwise aborts when it initialises the GPU; a value set before is kept. Several processes can use the GPU, but exchange GPU data through main memory

Shell hooks only set variables and print; they create no files.

## CUDA and the driver

The CUDA build of PETSc needs the NVIDIA driver's `libcuda.so.1` and `libnvidia-ml.so.1` even to be imported. On NixOS with `nixos.nvidia-offload` they are in `/run/opengl-driver/lib`, where the build looks. Without a driver the shell says so at entry, and nothing falls back to stub libraries; use `numerics-cpu` on machines without an NVIDIA GPU.

## Validation

`nix flake check` runs these in the Nix sandbox (`dev-env/checks.nix`, as `dev-env-*`): the sum of ranks with mpi4py on 1, 2 and 4 processes; a tridiagonal system with a manufactured solution solved with MUMPS through petsc4py on 1 and 2 processes and through PETSc's C interface built with CMake (relative error below 1e-10); the five smallest eigenvalues of the 1D Laplacian with slepc4py against the analytic values; an MPI program in Fortran; that the C program and petsc4py load the same PETSc and that each shell's closure contains exactly one; that only the CUDA variant reports CUDA; the two refusals; and that `ipykernel` imports.

For `openfoam` (`f1` to `f6`): `simpleFoam -help` reports v2512; the cavity tutorial runs with `blockMesh` and `icoFoam` to its last time; the same case on 4 processes (`decomposePar`, `mpirun -np 4 icoFoam -parallel`, `reconstructPar`) gives the fields of the serial run to the six digits written, with the linear solvers of both runs set to 1e-12, because at the tutorial's own tolerances a parallel run differs from a serial one in the last digits; a program of our own is compiled with `wmake`, installed into the user folder and reports the 400 cells and the volume of the cavity; with `numerics-cpu` in the same shell there is one MPI launcher on `PATH`, OpenFOAM and PETSc link the same `libmpi`, the closure holds one Open MPI, and the parallel cavity, the C program with PETSc and MUMPS through petsc4py all run; and the user folder is the hidden folder of the home in a terminal, `.openfoam/` of the project when the home is in memory, and a named folder when one is set, and comes first on both paths.

Run by hand on the laptop's GPU under Ubuntu, with the driver libraries passed explicitly (2026-11-12): conjugate gradients with Jacobi on the GPU on 1 and 2 processes (relative error 8.4e-13, equal to the CPU result to 1.3e-16), MUMPS in the CUDA build, a CUDA program compiled with `nvcc` (identical to the CPU result), and SLEPc. Also by hand: `uv add matplotlib cadquery` on top of the shell's packages (the numerics packages stay the shell's, the others land in `.venv`; `dev-env/tests/import_origins.py` prints where each comes from), a CadQuery box with the expected volume and STL (`dev-env/tests/b10_cadquery.py`), and `uv add numpy` with the `python` block alone.

Run by hand for `openfoam` under Ubuntu (2026-11-14), with v2606 compiled for the trial, in a project made from the template: the checks' steps outside the Nix sandbox, a `coded` function object, which OpenFOAM compiles while the solver runs, `simpleFoam` on 4 processes decomposed with Scotch (pitzDaily), `snappyHexMesh` through the `Allrun` of the flange tutorial, and the parallel cavity in a shell with `numerics-cuda`. Not tested for `openfoam`: those steps with v2512 (only the checks ran with it), the other tutorials, PETSc on the GPU beside OpenFOAM, PyPI wheels in a shell that carries OpenFOAM's `LD_LIBRARY_PATH`, the choice of the user folder in a real pi sandbox, and the block on NixOS itself.

Not tested: multigrid or hypre on GPU matrices, GPU factorisations, SLEPc with GPU types, a notebook kernel in VSCodium, and the GPU tests on NixOS itself. The GPU tests are `dev-env/tests/ksp_tridiag.py` with `-vec_type cuda -mat_type aijcusparse`, `g1_import_device.py` and `g7_saxpy.cu`.
