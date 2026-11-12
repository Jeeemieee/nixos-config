"""G8: five smallest eigenvalues of the 1D Laplacian [-1, 2, -1] with SLEPc, CPU types."""

import sys

import numpy as np
import petsc4py
import slepc4py

petsc4py.init(sys.argv)
slepc4py.init(sys.argv)

from petsc4py import PETSc
from slepc4py import SLEPc

from common import librariesOutsideStore, tridiagonalCsr

# Declared problem and tolerance of G8
SIZE = 100
COUNT = 5
ERROR_TOLERANCE = 1e-10


def main() -> int:
    """Solve the eigenproblem, compare with the closed form and return the exit code."""
    ## Step 1. Assemble the Laplacian with CPU types
    _matrix_ = PETSc.Mat().create(comm=PETSc.COMM_SELF)
    _matrix_.setSizes([SIZE, SIZE])
    _matrix_.setType("aij")
    _matrix_.setPreallocationCSR(tridiagonalCsr(SIZE, 0, SIZE, 2.0, -1.0))
    _matrix_.assemble()


    ## Step 2. Solve with shift-and-invert around zero
    _eps_ = SLEPc.EPS().create(comm=PETSc.COMM_SELF)
    _eps_.setOperators(_matrix_)
    _eps_.setProblemType(SLEPc.EPS.ProblemType.HEP)
    _eps_.setDimensions(nev=COUNT)
    _eps_.setTolerances(tol=1e-12)
    _eps_.setWhichEigenpairs(SLEPc.EPS.Which.TARGET_MAGNITUDE)
    _eps_.setTarget(0.0)
    _eps_.getST().setType("sinvert")
    _eps_.solve()


    ## Step 3. Compare with the closed form 2 - 2 cos(k pi / (n + 1))
    _converged_ = _eps_.getConverged()
    _computed_ = np.sort([_eps_.getEigenvalue(_index_).real for _index_ in range(min(_converged_, COUNT))])
    _exact_ = 2.0 - 2.0 * np.cos(np.arange(1, COUNT + 1) * np.pi / (SIZE + 1))
    _passed_ = (_converged_ >= COUNT)
    print("slepc version:", SLEPc.Sys.getVersion(), "matrix type:", _matrix_.getType())
    print("eps type:", _eps_.getType(), "st type:", _eps_.getST().getType(), "converged:", _converged_)
    for _index_ in range(len(_computed_)):
        _error_ = abs(_computed_[_index_] - _exact_[_index_]) / abs(_exact_[_index_])
        _passed_ = (_passed_ and (_error_ < ERROR_TOLERANCE))
        print(
            f"k={_index_ + 1}",
            "computed:", repr(float(_computed_[_index_])),
            "exact:", repr(float(_exact_[_index_])),
            "relative error:", repr(float(_error_)),
        )
    for _path_ in librariesOutsideStore():
        print("loaded outside /nix/store:", _path_)
    print("G8", "PASS" if _passed_ else "FAIL")
    return 0 if _passed_ else 1


if (__name__ == "__main__"):
    sys.exit(main())
