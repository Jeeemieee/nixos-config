# Project

Development environment from Nix building blocks, loaded by direnv.

## First use

1. Choose the blocks in `flake.nix`: `python`, `cpp`, and at most one of
   `numerics-cpu` and `numerics-cuda`. Extra tools go into `packages`.
2. Run `direnv allow`. The first load downloads the tools and writes `flake.lock`.

## Python packages

The shell provides Python 3.13, `uv` and `ipykernel`. With a numerics block it also
provides `numpy`, `scipy`, `mpi4py`, `petsc4py` and `slepc4py`; these belong to the
PETSc build of the shell and must not be installed from PyPI.

1. Create the environment once, so that it sees the packages of the shell:

   ```
   uv venv --system-site-packages
   ```

2. Add packages from PyPI and run with them:

   ```
   uv add matplotlib
   uv run python script.py
   ```

`pyproject.toml` lists the five numerics packages under `exclude-dependencies`, which
keeps uv from installing its own copies. Without a numerics block, remove that list.

If `.venv` was created without `--system-site-packages`, the five packages cannot be
imported; delete `.venv` and repeat step 1. The same holds after `nix flake update blocks`:
`.venv` still points at the previous Python, and once that is garbage-collected uv
quietly creates a new environment without the shell's packages. Delete `.venv` and
repeat step 1 after every update of the blocks.

With the `exclude-dependencies` list, uv does not check whether a package from PyPI
accepts the shell's numpy or scipy version; a package that needs another version fails
when it is imported, not when it is installed.

The project must be a Git repository with `.venv/` and `.direnv/` ignored (the
`.gitignore` here does that); otherwise every reload copies the whole folder, virtual
environment included, into the Nix store.

## CUDA

`numerics-cuda` needs the NVIDIA driver library `libcuda.so.1`. The shell says so at
entry when it finds none; PETSc cannot be loaded then.
