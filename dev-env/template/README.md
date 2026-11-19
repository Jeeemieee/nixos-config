# Project

Development environment from Nix building blocks, loaded by direnv.

## First use

1. Choose the blocks in `environment/nix/flake.nix`: `python`, `cpp`, `openfoam`, and at most one of
   `numerics-cpu` and `numerics-cuda`. Extra tools go into `packages`.
2. Run `direnv allow`, then `nix-direnv-reload`. The first load downloads the tools and writes
   `environment/nix/flake.lock`.
3. After every change of `flake.nix` or `flake.lock`, run `nix-direnv-reload` again: the environment is not reloaded by itself.

`environment/nix/` holds only `flake.nix` and `flake.lock`. `.envrc` enters it as a folder of its own, so only
those two files are copied into the Nix store, not the project. Other environment files, such as Docker's, go
beside it in `environment/`.

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

Keep `.venv/` and `.direnv/` ignored (the `.gitignore` here does that), and keep every other
file out of `environment/nix/`: whatever lies there is copied into the Nix store at every reload.

## CUDA

`numerics-cuda` needs the NVIDIA driver library `libcuda.so.1`. The shell says so at
entry when it finds none; PETSc cannot be loaded then.
