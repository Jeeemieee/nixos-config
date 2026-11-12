"""Shared helpers of the GPU validation tests: NumPy oracles and process inspection."""

from typing import Annotated

import numpy as np


def exactSolution(
    rowStart: Annotated[
        int,
        "First global row index (inclusive)",
    ],
    rowEnd: Annotated[
        int,
        "Last global row index (exclusive)",
    ],
) -> np.ndarray:
    """Return the manufactured solution x*_i = sin(i) for the given rows."""
    # Evaluate the manufactured solution on the global indices
    return np.sin(np.arange(rowStart, rowEnd, dtype=np.float64))


def rightHandSide(
    size: Annotated[
        int,
        "Global size n of the tridiagonal [-1, 4, -1] matrix",
    ],
    rowStart: Annotated[
        int,
        "First global row index (inclusive)",
    ],
    rowEnd: Annotated[
        int,
        "Last global row index (exclusive)",
    ],
) -> np.ndarray:
    """Return b = A x* for the given rows, computed with NumPy only."""
    ## Step 1. Evaluate the stencil terms
    # Diagonal term 4 x*_i
    _rows_ = np.arange(rowStart, rowEnd, dtype=np.float64)
    _rhs_ = 4.0 * np.sin(_rows_)

    # Lower neighbour -x*_(i-1), absent in the first global row
    _lower_ = -np.sin(_rows_ - 1.0)
    _lower_[_rows_ == 0.0] = 0.0

    # Upper neighbour -x*_(i+1), absent in the last global row
    _upper_ = -np.sin(_rows_ + 1.0)
    _upper_[_rows_ == float(size - 1)] = 0.0


    ## Step 2. Sum the terms
    return _rhs_ + _lower_ + _upper_


def tridiagonalCsr(
    size: Annotated[
        int,
        "Global size n of the matrix",
    ],
    rowStart: Annotated[
        int,
        "First global row index (inclusive)",
    ],
    rowEnd: Annotated[
        int,
        "Last global row index (exclusive)",
    ],
    diagonal: Annotated[
        float,
        "Value on the diagonal",
    ],
    offDiagonal: Annotated[
        float,
        "Value on both off-diagonals",
    ],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the CSR arrays (row pointer, global columns, values) of the given rows."""
    ## Step 1. Build all candidate entries row by row
    # Three candidate columns per row: i-1, i, i+1
    _rows_ = np.arange(rowStart, rowEnd, dtype=np.int64)
    _columns_ = np.stack([_rows_ - 1, _rows_, _rows_ + 1], axis=1)
    _values_ = np.tile(np.array([offDiagonal, diagonal, offDiagonal]), (_rows_.size, 1))


    ## Step 2. Drop the entries outside the matrix
    # Keep columns within [0, n)
    _keep_ = (_columns_ >= 0) & (_columns_ < size)

    # Row pointer from the number of kept entries per row
    _rowPointer_ = np.concatenate(([0], np.cumsum(_keep_.sum(axis=1))))

    return (
        _rowPointer_.astype(np.int32),
        _columns_[_keep_].astype(np.int32),
        _values_[_keep_].astype(np.float64),
    )


def relativeError(
    computed: Annotated[
        np.ndarray,
        "Computed values",
    ],
    reference: Annotated[
        np.ndarray,
        "Reference values of the same shape",
    ],
) -> float:
    """Return ||computed - reference||_2 / ||reference||_2."""
    # Euclidean norm of the difference relative to the reference
    return float(np.linalg.norm(computed - reference) / np.linalg.norm(reference))


def librariesOutsideStore() -> list[str]:
    """Return the shared objects mapped into this process that are not in /nix/store."""
    # Collect the file-backed mappings of the current process
    _paths_ = set()
    with open("/proc/self/maps") as _maps_:
        for _line_ in _maps_:
            _fields_ = _line_.split(maxsplit=5)
            if (len(_fields_) == 6):
                _paths_.add(_fields_[5].strip())

    # Keep shared objects that do not come from the Nix store
    return sorted(
        _path_
        for _path_ in _paths_
        if ((".so" in _path_) and not _path_.startswith("/nix/store/"))
    )
