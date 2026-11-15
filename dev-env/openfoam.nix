# OpenFOAM building block
#
# What it is    OpenFOAM from ESI (openfoam.com), as nixpkgs-unstable packages it: the binary cache serves it, nothing is
#               compiled here
# Who uses it   dev-env/dev-shell.nix, for a shell with the openfoam block
# A user adds   Nothing. A newer release than nixpkgs has would be compiled on the machine, about an hour on 8 cores at
#               every update of the development environments: add `.overrideAttrs (old: { version = …; src = …; })`
#               with the release's source
# Protected     Yes, with all of dev-env/ (docs/UPKEEP.md)
# The release that the checks expect is written in dev-env/checks.nix (openfoamRelease), not read from here
{ pkgs }:
pkgs.openfoam-unwrapped.override {
  # The MPI of the numerics blocks, so that a shell holds one MPI
  openmpi = pkgs.mpi;
}
