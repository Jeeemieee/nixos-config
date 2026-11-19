# Project development environments
#
# What it is    The building blocks' flake in dev-env/, offered again under this repository's own name, and its checks
# Who uses it   Project flakes through "github:Jeeemieee/nixos-config?dir=dev-env" (the old address without ?dir still works)
# A project adds Its chosen blocks and any extra packages described in docs/DEV-ENVIRONMENTS.md
# Protected     Yes: the library can run shell hooks in the user's own project shell (docs/UPKEEP.md)
{ inputs, lib, ... }:
let
  # The library of the blocks' flake, built from their own pin; nixpkgs-unstable follows that pin (flake.nix)
  inherit (inputs.dev-env.lib) devShell;

  # The pin as the blocks' own lock holds it, and as this repository's lock holds its copy
  # Each is the locked source of nixpkgs: owner, repository, revision and hash
  blocksPin = lock: lock.nodes.${lock.nodes.root.inputs.nixpkgs}.locked;
  copiedPin = lock: lock.nodes.${lock.nodes.${lock.nodes.root.inputs.dev-env}.inputs.nixpkgs}.locked;
  inStep = rootLock: blocksLock: copiedPin rootLock == blocksPin blocksLock;
  rootLock = lib.importJSON ../../flake.lock;
  blocksLock = lib.importJSON ../../dev-env/flake.lock;
in
{
  ## Part 1. Public library and template
  # The old address keeps working for projects that have not moved to ?dir=dev-env
  flake.lib.devShell = devShell;
  flake.templates.project = inputs.dev-env.templates.project;

  ## Part 2. Development-environment checks
  perSystem =
    { system, pkgs, ... }:
    {
      # Test the supported blocks, combinations, one-PETSc rule and explicit refusals in the Nix sandbox
      # For OpenFOAM: serial, parallel, with wmake, beside PETSc, and where it keeps the user's own solvers
      checks =
        lib.mapAttrs' (name: lib.nameValuePair "dev-env-${name}") (
          import ../../dev-env/checks.nix {
            nixpkgs = inputs.nixpkgs-unstable;
            inherit system devShell;
          }
        )
        // {
          # The checks above use this lock's copy of the blocks' pin; projects get the blocks' own lock
          # Refuse when the two differ, and show with a control that a differing pin is noticed
          dev-env-lock-in-step =
            let
              control = lib.recursiveUpdate blocksLock {
                nodes.${blocksLock.nodes.root.inputs.nixpkgs}.locked.rev =
                  "0000000000000000000000000000000000000000";
              };
            in
            assert lib.assertMsg (
              !(inStep rootLock control)
            ) "dev-env-lock-in-step: the control with another pin was not noticed";
            assert lib.assertMsg (inStep rootLock blocksLock) (
              "dev-env-lock-in-step: flake.lock holds another nixpkgs for dev-env than dev-env/flake.lock; "
              + "run: config update dev"
            );
            pkgs.runCommand "dev-env-lock-in-step" { } "touch $out";
        };
    };
}
