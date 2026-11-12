"""B1: sum of the MPI ranks with mpi4py; expected n(n-1)/2 for n ranks."""

import sys

from mpi4py import MPI


def main() -> int:
    """Reduce the rank numbers over all ranks and return the process exit code."""
    # Sum of the ranks 0..n-1 through MPI
    _comm_ = MPI.COMM_WORLD
    _size_ = _comm_.Get_size()
    _sum_ = _comm_.allreduce(_comm_.Get_rank(), op=MPI.SUM)

    # Closed form, independent of MPI
    _expected_ = (_size_ * (_size_ - 1)) // 2
    _passed_ = (_sum_ == _expected_)
    if (_comm_.Get_rank() == 0):
        print("ranks:", _size_, "sum of ranks:", _sum_, "expected:", _expected_)
        print("B1", "PASS" if _passed_ else "FAIL")
    return 0 if _passed_ else 1


if (__name__ == "__main__"):
    sys.exit(main())
