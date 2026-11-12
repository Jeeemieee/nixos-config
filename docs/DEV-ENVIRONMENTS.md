# Development environments

A project gets its tools from building blocks that are defined once, in `dev-env/`, and referenced by every project. The environment is active only inside the project folder (direnv), nothing is installed system-wide, and projects on the same revision of this repository share one build of every tool.

## Blocks

| Block | Contents |
| --- | --- |
| `python` | Python 3.13, `uv`, `ipykernel`; PyPI wheels find libstdc++, zlib, libGL, libX11 and expat through a library path that only Python processes get |
| `cpp` | C and C++ compilers, `gfortran`, CMake, Ninja, pkg-config, clangd (`clang-tools`), gdb; without the `fortify` hardening, so CMake Debug builds are not optimised |
| `numerics-cpu` | Open MPI, PETSc 3.25 and SLEPc with MUMPS, ScaLAPACK, METIS and hypre, unmodified from nixpkgs (binary cache); with `python` also numpy, scipy, mpi4py, petsc4py and slepc4py |
| `numerics-cuda` | The same with PETSc and SLEPc built for CUDA 12.6 (GPU architecture 8.9, the laptop's RTX 3500 Ada), plus `nvcc` and the CUDA libraries for the project's own code |

A project chooses any of `python` and `cpp`, and at most one numerics block. Both numerics blocks together, or an unknown name, fail with a message. Extra tools go into `packages`.

The blocks use the `nixpkgs-unstable` input, independent of the hosts' package set. The CUDA packages are unfree; their names are allowed inside `dev-env/cuda-overlay.nix` only, not on the hosts' allowlist. The first use of `numerics-cuda` on a machine builds PETSc with CUDA (about a quarter of an hour).

## Start a project

```bash
mkdir ~/projects/<name> && cd ~/projects/<name> && git init
nix flake init -t github:Jeeemieee/nixos-config#project
```

Choose the blocks in `flake.nix`, then `direnv allow`. The template's `README.md` describes the Python steps: `uv venv --system-site-packages` once, then `uv add <package>`; the numerics packages come from the shell and are listed under `exclude-dependencies` in `pyproject.toml`, so uv does not install its own copies.

Update the blocks of a project with `nix flake update blocks`, then delete `.venv` and create it again.

## What a shell sets

- `PYTHONPATH` is unset: nixpkgs would fill it with the shell's packages, which would then override the project's `.venv`
- Open MPI is first on `PATH`, before the Python environment's own `mpiexec`, which carries Python's library path
- `PETSC_DIR` and `SLEPC_DIR` point at the builds that petsc4py and slepc4py use: one PETSc and one SLEPc per shell, also for C, C++ and Fortran (pkg-config)
- `UV_PYTHON` is the shell's Python and `UV_PYTHON_DOWNLOADS=never`: uv never downloads a Python
- `numerics-cuda`: `-use_gpu_aware_mpi 0` is prepended to `PETSC_OPTIONS`, because nixpkgs' Open MPI is not GPU-aware and PETSc otherwise aborts when it initialises the GPU; a value set before is kept. Several processes can use the GPU, but exchange GPU data through main memory

Shell hooks only set variables and print; they create no files.

## CUDA and the driver

The CUDA build of PETSc needs the NVIDIA driver's `libcuda.so.1` and `libnvidia-ml.so.1` even to be imported. On NixOS with `nixos.nvidia-offload` they are in `/run/opengl-driver/lib`, where the build looks. Without a driver the shell says so at entry, and nothing falls back to stub libraries; use `numerics-cpu` on machines without an NVIDIA GPU.

## Validation

`nix flake check` runs these in the Nix sandbox (`dev-env/checks.nix`, as `dev-env-*`): the sum of ranks with mpi4py on 1, 2 and 4 processes; a tridiagonal system with a manufactured solution solved with MUMPS through petsc4py on 1 and 2 processes and through PETSc's C interface built with CMake (relative error below 1e-10); the five smallest eigenvalues of the 1D Laplacian with slepc4py against the analytic values; an MPI program in Fortran; that the C program and petsc4py load the same PETSc and that each shell's closure contains exactly one; that only the CUDA variant reports CUDA; the two refusals; and that `ipykernel` imports.

Run by hand on the laptop's GPU under Ubuntu, with the driver libraries passed explicitly (2026-11-12): conjugate gradients with Jacobi on the GPU on 1 and 2 processes (relative error 8.4e-13, equal to the CPU result to 1.3e-16), MUMPS in the CUDA build, a CUDA program compiled with `nvcc` (identical to the CPU result), and SLEPc. Also by hand: `uv add matplotlib cadquery` on top of the shell's packages (the numerics packages stay the shell's, the others land in `.venv`), a CadQuery box with the expected volume and STL, and `uv add numpy` with the `python` block alone.

Not tested: multigrid or hypre on GPU matrices, GPU factorisations, SLEPc with GPU types, a notebook kernel in VSCodium, and the GPU tests on NixOS itself. The GPU tests are `dev-env/tests/ksp_tridiag.py` with `-vec_type cuda -mat_type aijcusparse`, `g1_import_device.py` and `g7_saxpy.cu`.
