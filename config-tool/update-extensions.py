# Moves pi's extensions to their newest versions: update-extensions.py <pi.nix>
# For every extension that is fixed with `npm "<name>" "<version>" "<hash>"`, the registry is asked for the newest version and
# its hash, and the two strings are replaced in the file. The check in the same file that names the versions pi must report,
# as "<name> <version>", follows: it then compares what the fetched packages say about themselves with what the registry announced
# Nothing else in the file is touched
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Annotated

REGISTRY = os.environ.get("CONFIG_NPM_REGISTRY", "https://registry.npmjs.org")
PIN = re.compile(r'npm "(?P<name>[^"]+)" "(?P<version>[^"]+)"(?P<gap>\s+)"(?P<hash>sha512-[A-Za-z0-9+/=]+)"')


def newest(
    name: Annotated[str, "The package's name on the registry"],
):
    """The newest version of a package and the hash of its archive"""
    _address_ = f"{REGISTRY}/{urllib.parse.quote(name, safe='@')}/latest"
    with urllib.request.urlopen(_address_, timeout=30) as _answer_:
        _package_ = json.load(_answer_)
    _version_, _hash_ = _package_["version"], _package_["dist"]["integrity"]
    # Both become text in a Nix file: refuse anything that is not a plain version and a sha512 hash
    if not re.fullmatch(r"[0-9A-Za-z.+-]+", _version_) or not re.fullmatch(r"sha512-[A-Za-z0-9+/=]+", _hash_):
        raise ValueError(f"the registry's answer for {name} is not a version and a sha512 hash")
    return _version_, _hash_


def main():
    if (len(sys.argv) != 2):
        sys.exit("usage: update-extensions.py <pi.nix>")
    _path_ = sys.argv[1]
    with open(_path_) as _file_:
        _text_ = _file_.read()
    _pins_ = list(PIN.finditer(_text_))
    if not _pins_:
        sys.exit(f"update-extensions: {_path_} fixes no extension in the expected form; nothing was changed")

    ## Step 1. Ask the registry for every fixed extension; any failure leaves the file as it is
    _found_ = {}
    for _pin_ in _pins_:
        try:
            _found_[_pin_["name"]] = newest(_pin_["name"])
        except (OSError, KeyError, ValueError) as _error_:
            sys.exit(f"update-extensions: {_pin_['name']}: {_error_}; nothing was changed")

    ## Step 2. Replace version and hash of each
    def replace(pin):
        _version_, _hash_ = _found_[pin["name"]]
        _state_ = "unchanged" if (_version_ == pin["version"]) else f"{pin['version']} -> {_version_}"
        print(f"  {pin['name']}: {_state_}")
        return f'npm "{pin["name"]}" "{_version_}"{pin["gap"]}"{_hash_}"'

    _new_ = PIN.sub(replace, _text_)
    for _pin_ in _pins_:
        _new_ = _new_.replace(f'"{_pin_["name"]} {_pin_["version"]}"', f'"{_pin_["name"]} {_found_[_pin_["name"]][0]}"')
    if (_new_ != _text_):
        with open(_path_, "w") as _file_:
            _file_.write(_new_)


if (__name__ == "__main__"):
    main()
