"""B9/B11: check where packages are imported from: the Nix store or the project's .venv."""

import argparse
import importlib
import sys


def main() -> int:
    """Import the named packages, compare their location and return the exit code."""
    # Packages expected from Nix and packages expected from the virtual environment
    _parser_ = argparse.ArgumentParser()
    _parser_.add_argument("--nix", default="", help="Comma-separated packages expected in /nix/store")
    _parser_.add_argument("--venv", default="", help="Comma-separated packages expected in .venv")
    _arguments_ = _parser_.parse_args()

    # Import every package and judge its file location
    _passed_ = True
    for _names_, _expected_ in ((_arguments_.nix, "nix"), (_arguments_.venv, "venv")):
        for _name_ in filter(None, _names_.split(",")):
            _file_ = importlib.import_module(_name_).__file__
            if (_expected_ == "nix"):
                _matches_ = _file_.startswith("/nix/store/")
            else:
                _matches_ = ("/.venv/" in _file_)
            _passed_ = (_passed_ and _matches_)
            print(f"{_name_}: expected {_expected_}, {'ok' if _matches_ else 'WRONG'}: {_file_}")

    print("origins", "PASS" if _passed_ else "FAIL")
    return 0 if _passed_ else 1


if (__name__ == "__main__"):
    sys.exit(main())
