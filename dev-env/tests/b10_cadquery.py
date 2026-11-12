"""B10: CadQuery box 10 x 20 x 30, exported to STL and read back with NumPy."""

import struct
import sys
from typing import Annotated

import numpy as np

import cadquery as cq

# Declared expectations of B10
SIZES = (10.0, 20.0, 30.0)
VOLUME = 6000.0
VOLUME_TOLERANCE = 1e-9
TRIANGLES = 12

# STL stores single-precision coordinates; 1e-6 is their resolution at these sizes
EXTENT_TOLERANCE = 1e-6


def readStl(
    path: Annotated[
        str,
        "STL file, ASCII or binary",
    ],
) -> np.ndarray:
    """Return the triangles of an STL file as array of shape (count, 3, 3), without CadQuery."""
    with open(path, "rb") as _file_:
        _data_ = _file_.read()

    # ASCII: every vertex is a line "vertex x y z"
    if (_data_[:5] == b"solid") and (b"facet" in _data_):
        _vertices_ = [
            [float(_word_) for _word_ in _line_.split()[1:4]]
            for _line_ in _data_.decode().splitlines()
            if _line_.strip().startswith("vertex")
        ]
        return np.array(_vertices_).reshape(-1, 3, 3)

    # Binary: 80-byte header, triangle count, then 50-byte records (normal, 3 vertices, attribute)
    (_count_,) = struct.unpack_from("<I", _data_, 80)
    _records_ = np.frombuffer(_data_, dtype=np.dtype([("values", "<f4", (4, 3)), ("attribute", "<u2")]), count=_count_, offset=84)
    return _records_["values"][:, 1:, :].astype(np.float64)


def main() -> int:
    """Build the box, check the volume, export, read back and return the exit code."""
    ## Step 1. Build the box and check its volume
    _box_ = cq.Workplane("XY").box(*SIZES)
    _volume_ = _box_.val().Volume()
    _volumeError_ = abs(_volume_ - VOLUME) / VOLUME
    print("cadquery:", cq.__version__, "from", cq.__file__)
    print("volume:", repr(_volume_), "relative error:", repr(_volumeError_))


    ## Step 2. Export to STL and read back independently
    cq.exporters.export(_box_, "b10_box.stl")
    _triangles_ = readStl("b10_box.stl")
    _points_ = _triangles_.reshape(-1, 3)
    _extents_ = _points_.max(axis=0) - _points_.min(axis=0)
    _extentError_ = float(np.abs(_extents_ - np.array(SIZES)).max())
    print("triangles:", len(_triangles_), "bounding box:", _extents_.tolist(), "largest deviation:", repr(_extentError_))


    ## Step 3. Judge
    _passed_ = (
        (_volumeError_ < VOLUME_TOLERANCE)
        and (len(_triangles_) == TRIANGLES)
        and (_extentError_ < EXTENT_TOLERANCE)
    )
    print("B10", "PASS" if _passed_ else "FAIL")
    return 0 if _passed_ else 1


if (__name__ == "__main__"):
    sys.exit(main())
