# The queue, as a worker sees it: hands a command to this sandbox's broker and waits for it (see docs/WORKERS.md)
#   queue run -- <command...>             one of the machine's slots
#   queue run --parallel -- <command...>  also the parallel token, for a command that runs concurrent processes itself
#   queue timing -- <command...>          one timing job at a time, alone on the timing cores
#   queue exclusive -- <command...>       the whole machine: waits until no queued job runs
#   queue acceptance                      an implementer: the tests that were approved with its intent, taken from the project,
#                                         on this copy as it is committed; with --all, a manager: the project's whole suite
#   queue status                          which slots are taken
# The job runs in a second sandbox with this worker's view, started by the broker outside; it gets this command's own input and output
# Inside a job, `queue` runs its command directly: a job has no broker, and waiting for a second slot while holding one would deadlock
import json
import os
import re
import socket
import struct
import sys
from typing import Annotated

USAGE = "usage: queue run [--parallel] -- <command...>, queue timing -- <command...>, queue exclusive -- <command...>, queue acceptance [--all], or queue status"


def fail(
    message: Annotated[str, "Why nothing was run"],
):
    print(f"queue: {message}", file=sys.stderr)
    sys.exit(2)


def main():
    ## Step 1. Read the command line
    _arguments_ = sys.argv[1:]
    if not _arguments_ or (_arguments_[0] not in ("run", "timing", "exclusive", "acceptance", "status")):
        fail(USAGE)
    _mode_ = _arguments_.pop(0)
    if (_mode_ == "run") and _arguments_ and (_arguments_[0] == "--parallel"):
        _mode_ = "run-parallel"
        _arguments_.pop(0)
    if (_mode_ == "acceptance"):
        # What an acceptance run runs is not this command's to say
        if _arguments_ and (_arguments_ != ["--all"]):
            fail(USAGE)
        if os.environ.get("WORKER_JOB"):
            fail("an acceptance run is started from the worker's session, not from inside a job; nothing was run")
        _mode_ = "acceptance-all" if _arguments_ else "acceptance"
        _arguments_ = []
    if _arguments_ and (_arguments_[0] == "--"):
        _arguments_.pop(0)
    if (_mode_ not in ("status", "acceptance", "acceptance-all")) and not _arguments_:
        fail(USAGE)

    ## Step 2. Inside a job there is no broker: run directly, in the job's own resource group
    if (_mode_ != "status") and os.environ.get("WORKER_JOB"):
        print(f"queue: already inside a '{os.environ['WORKER_JOB']}' job; running this command directly", file=sys.stderr)
        os.execvp(_arguments_[0], _arguments_)

    ## Step 3. Hand the request to the broker, with this process's own input and output
    _path_ = os.environ.get("WORKER_QUEUE_SOCKET")
    if not _path_:
        fail("this is not a pi sandbox with a broker (WORKER_QUEUE_SOCKET is not set); nothing was run")
    _connection_ = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _connection_.connect(_path_)
    except OSError as _error_:
        fail(f"the broker of this sandbox does not answer ({_error_}); nothing was run")
    # The broker takes only names that are plain variable names; others, such as a shell's exported functions, stay behind, and that is said
    _environment_ = {_name_: _value_ for _name_, _value_ in os.environ.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _name_)}
    _left_ = sorted(set(os.environ) - set(_environment_))
    if _left_:
        print(f"queue: not passed to the job, because their names are not plain variable names: {', '.join(_left_)[:300]}", file=sys.stderr)
    _body_ = json.dumps({"mode": _mode_, "command": _arguments_, "folder": os.getcwd(), "environment": _environment_}).encode()
    _message_ = struct.pack(">I", len(_body_)) + _body_
    # The descriptors travel with the first part; the rest of a long request follows
    _sent_ = socket.send_fds(_connection_, [_message_[:32768]], [0, 1, 2])
    if (_sent_ < len(_message_)):
        _connection_.sendall(_message_[_sent_:])

    ## Step 4. Wait for the one answer
    _answer_ = b""
    while not _answer_.endswith(b"\n"):
        _part_ = _connection_.recv(65536)
        if not _part_:
            fail("the broker went away before the job ended")
        _answer_ += _part_
    _answer_ = json.loads(_answer_.decode())
    if ("refused" in _answer_):
        fail(f"refused: {_answer_['refused']}")
    if ("status" in _answer_):
        print(_answer_["status"])
        sys.exit(0)
    # What the broker has to say about a job that ran: it was stopped at a time limit, or its end could not be recorded
    if ("note" in _answer_):
        print(f"queue: {_answer_['note']}", file=sys.stderr)
    sys.exit(_answer_["exit"])


if (__name__ == "__main__"):
    main()
