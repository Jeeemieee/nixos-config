# A manager's read-only route to every worker of its project, through this sandbox's broker
#   worker-read [--sha256] [--offset <bytes>] <branch>/<name> <reports|records> [<path>]
# A directory is listed as one JSON string per entry. A regular file is written as bytes, in bounded pieces.
import json
import os
import re
import socket
import struct
import sys
from typing import Annotated

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
USAGE = "usage: worker-read [--sha256] [--offset <bytes>] <branch>/<name> <reports|records> [<path>]"


def fail(
    message: Annotated[str, "Why nothing was read"],
):
    print(f"worker-read: {message}", file=sys.stderr)
    sys.exit(2)


def main():
    ## Step 1. Check the requested worker, part, path and read mode
    _arguments_ = sys.argv[1:]
    _digest_ = False
    _offset_ = 0
    while _arguments_ and _arguments_[0].startswith("--"):
        _option_ = _arguments_.pop(0)
        if (_option_ == "--sha256"):
            _digest_ = True
        elif (_option_ == "--offset"):
            if not _arguments_:
                fail(USAGE)
            try:
                _offset_ = int(_arguments_.pop(0))
            except ValueError:
                fail("--offset is a non-negative byte count")
            if (_offset_ < 0):
                fail("--offset is a non-negative byte count")
        else:
            fail(USAGE)
    if (len(_arguments_) not in (2, 3)):
        fail(USAGE)
    _worker_, _part_ = _arguments_[:2]
    _path_ = _arguments_[2] if (len(_arguments_) == 3) else ""
    _names_ = _worker_.split("/")
    if (len(_names_) != 2) or not all(NAME.fullmatch(_name_) for _name_ in _names_):
        fail("the worker is <branch>/<name>, each 1 to 48 letters, digits, '.', '_' or '-'")
    if (_part_ not in ("reports", "records")):
        fail("the part is reports or records")
    _parts_ = _path_.split("/") if _path_ else []
    if _path_.startswith("/") or any((_part_ in ("", ".", "..")) for _part_ in _parts_):
        fail(f"the path stays below {_part_}")

    ## Step 2. Send the closed request to this sandbox's broker
    _socket_ = os.environ.get("WORKER_QUEUE_SOCKET")
    if not _socket_:
        fail("this is not a worker sandbox with a broker; nothing was read")
    _request_ = {
        "mode": "worker-read",
        "command": [*_names_, _part_, _path_, str(_offset_), "sha256" if _digest_ else "read"],
        "folder": "/",
        "environment": {},
    }
    _body_ = json.dumps(_request_).encode()
    _message_ = struct.pack(">I", len(_body_)) + _body_
    _connection_ = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _connection_.connect(_socket_)
    except OSError as _error_:
        fail(f"the broker of this sandbox does not answer ({_error_}); nothing was read")
    _sent_ = socket.send_fds(_connection_, [_message_[:32768]], [0, 1, 2])
    if (_sent_ < len(_message_)):
        _connection_.sendall(_message_[_sent_:])

    ## Step 3. Report the broker's one answer after it has written the requested data
    _answer_ = b""
    while not _answer_.endswith(b"\n"):
        _part_ = _connection_.recv(65536)
        if not _part_:
            fail("the broker went away before the read ended")
        _answer_ += _part_
    try:
        _result_ = json.loads(_answer_.decode())
    except (UnicodeDecodeError, ValueError):
        fail("the broker returned no valid answer")
    if ("refused" in _result_):
        fail(f"refused: {_result_['refused']}")
    if ("read" not in _result_):
        fail("the broker returned no read result")
    if _result_["read"].get("more"):
        print(f"worker-read: {_result_['read']['bytes']} bytes read; more remains; continue with --offset {_result_['read']['nextOffset']}", file=sys.stderr)


if (__name__ == "__main__"):
    main()
