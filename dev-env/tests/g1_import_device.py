"""G1: import petsc4py in the CUDA environment and create a CUDA device and vector."""

import sys

import petsc4py

petsc4py.init(sys.argv)

from petsc4py import PETSc

from common import librariesOutsideStore


def main() -> int:
    """Run G1 and return the process exit code."""
    ## Step 1. Report the build
    # The import above is the first half of the criterion
    print("import petsc4py.PETSc: ok, PETSc version", PETSc.Sys.getVersion())


    ## Step 2. Create a CUDA device
    # Configure the device explicitly so that a driver problem shows up here
    _device_ = PETSc.Device.create(PETSc.Device.Type.CUDA)
    _device_.configure()
    print("device type:", _device_.getDeviceType(), "device id:", _device_.getDeviceId())


    ## Step 3. Create a CUDA vector
    # Sequential vector of type cuda
    _vector_ = PETSc.Vec().create(comm=PETSc.COMM_SELF)
    _vector_.setSizes(10)
    _vector_.setType("cuda")
    _vector_.set(1.0)
    _vectorType_ = _vector_.getType()
    print("vector type:", _vectorType_)
    print("norm of ten ones computed on the device:", repr(_vector_.norm()))


    ## Step 4. Report what was loaded from outside the Nix store
    for _path_ in librariesOutsideStore():
        print("loaded outside /nix/store:", _path_)


    ## Step 5. Judge
    _passed_ = (_vectorType_ == "seqcuda")
    print("G1", "PASS" if _passed_ else "FAIL")
    return 0 if _passed_ else 1


if (__name__ == "__main__"):
    sys.exit(main())
