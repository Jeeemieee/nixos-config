"""G2-G6: solve the tridiagonal [-1, 4, -1] system and compare with the NumPy oracle.

The vector and matrix types come from the PETSc options -vec_type and -mat_type; the
solver is fixed by --solver so that a command line cannot swap it silently.
"""

import argparse
import sys
import time

import numpy as np
import petsc4py

# Split the test's own arguments from the PETSc options
_parser_ = argparse.ArgumentParser()
_parser_.add_argument("--label", required=True, help="Test label printed in the verdict")
_parser_.add_argument("--n", type=int, required=True, help="Global problem size")
_parser_.add_argument("--solver", choices=["cg-jacobi", "mumps"], required=True)
_parser_.add_argument("--expect-vec", required=True, help="Expected PETSc vector type")
_parser_.add_argument("--expect-mat", required=True, help="Expected PETSc matrix type")
_parser_.add_argument("--save", default=None, help="Write the solution to this .npy file")
_arguments_, _petscOptions_ = _parser_.parse_known_args()

petsc4py.init([sys.argv[0]] + _petscOptions_)

from petsc4py import PETSc

from common import (
    exactSolution,
    librariesOutsideStore,
    relativeError,
    rightHandSide,
    tridiagonalCsr,
)

# Declared tolerance of G2-G5 on the relative error
ERROR_TOLERANCE = 1e-10


def main(
    arguments: argparse.Namespace,
) -> int:
    """Assemble, solve, compare with the oracle and return the process exit code."""
    ## Step 1. Create the vectors
    # Row layout decided by PETSc, type from -vec_type
    _comm_ = PETSc.COMM_WORLD
    _rhs_ = PETSc.Vec().create(comm=_comm_)
    _rhs_.setSizes(arguments.n)
    _rhs_.setFromOptions()
    _rowStart_, _rowEnd_ = _rhs_.getOwnershipRange()
    _localSize_ = _rowEnd_ - _rowStart_

    # Right-hand side b = A x* from the NumPy oracle
    _rhs_.setArray(rightHandSide(arguments.n, _rowStart_, _rowEnd_))
    _solution_ = _rhs_.duplicate()


    ## Step 2. Assemble the matrix
    # Same row layout as the vectors, type from -mat_type, entries computed with NumPy
    _matrix_ = PETSc.Mat().create(comm=_comm_)
    _matrix_.setSizes(((_localSize_, arguments.n), (_localSize_, arguments.n)))
    _matrix_.setFromOptions()
    _matrix_.setPreallocationCSR(tridiagonalCsr(arguments.n, _rowStart_, _rowEnd_, 4.0, -1.0))
    _matrix_.assemble()


    ## Step 3. Assert the types before solving
    _vectorType_ = _solution_.getType()
    _matrixType_ = _matrix_.getType()
    assert (_vectorType_ == arguments.expect_vec), f"vector type {_vectorType_}"
    assert (_matrixType_ == arguments.expect_mat), f"matrix type {_matrixType_}"


    ## Step 4. Solve
    # Solver fixed by the test declaration
    _ksp_ = PETSc.KSP().create(comm=_comm_)
    _ksp_.setOperators(_matrix_)
    _pc_ = _ksp_.getPC()
    if (arguments.solver == "cg-jacobi"):
        _ksp_.setType("cg")
        _pc_.setType("jacobi")
        _ksp_.setTolerances(rtol=1e-12)
    else:
        _ksp_.setType("preonly")
        _pc_.setType("lu")
        _pc_.setFactorSolverType("mumps")

    # Time the solve alone
    _solveStart_ = time.perf_counter()
    _ksp_.solve(_rhs_, _solution_)
    _solveSeconds_ = time.perf_counter() - _solveStart_
    _reason_ = _ksp_.getConvergedReason()


    ## Step 5. Gather the solution on rank 0
    _scatter_, _gathered_ = PETSc.Scatter.toZero(_solution_)
    _scatter_.scatter(_solution_, _gathered_, PETSc.InsertMode.INSERT, PETSc.ScatterMode.FORWARD)


    ## Step 6. Compare with the oracle on rank 0
    _passed_ = True
    if (_comm_.getRank() == 0):
        _computed_ = np.array(_gathered_.getArray(readonly=True))
        _error_ = relativeError(_computed_, exactSolution(0, arguments.n))
        _factorType_ = _pc_.getFactorSolverType() if (arguments.solver == "mumps") else None
        _passed_ = ((_reason_ > 0) and (_error_ < ERROR_TOLERANCE))
        if (arguments.solver == "mumps"):
            _passed_ = (_passed_ and (_factorType_ == "mumps"))

        # Report
        print("ranks:", _comm_.getSize(), "n:", arguments.n)
        print("vector type:", _vectorType_, "matrix type:", _matrixType_)
        print("ksp:", _ksp_.getType(), "pc:", _pc_.getType(), "factor solver:", _factorType_)
        print("converged reason:", _reason_, "iterations:", _ksp_.getIterationNumber())
        print("relative error:", repr(_error_), "tolerance:", ERROR_TOLERANCE)
        print("solve seconds:", f"{_solveSeconds_:.4f}")
        for _path_ in librariesOutsideStore():
            print("loaded outside /nix/store:", _path_)
        if (arguments.save is not None):
            np.save(arguments.save, _computed_)
        print(arguments.label, "PASS" if _passed_ else "FAIL")

    return 0 if _passed_ else 1


if (__name__ == "__main__"):
    sys.exit(main(_arguments_))
