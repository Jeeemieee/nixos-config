"""B6: print the libpetsc file that petsc4py loads into the Python process."""

import os
import sys

from petsc4py import PETSc  # noqa: F401


def main() -> int:
    """Print the resolved path of the mapped libpetsc and return the exit code."""
    # File-backed mappings of this process that belong to libpetsc
    _paths_ = set()
    with open("/proc/self/maps") as _maps_:
        for _line_ in _maps_:
            _fields_ = _line_.split(maxsplit=5)
            if ((len(_fields_) == 6) and ("/libpetsc.so" in _fields_[5])):
                _paths_.add(os.path.realpath(_fields_[5].strip()))

    # Exactly one PETSc library is expected in the process
    for _path_ in sorted(_paths_):
        print(_path_)
    return 0 if (len(_paths_) == 1) else 1


if (__name__ == "__main__"):
    sys.exit(main())
