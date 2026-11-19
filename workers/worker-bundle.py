# A manager's bounded route to one worker's committed branch through this sandbox's broker
#   worker-bundle <branch>/<name> > <bundle>
# Its internal forms run only as the broker's fixed commands inside checked Git sandboxes
import json
import os
import re
import socket
import struct
import subprocess
import sys
from typing import Annotated

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
HISTORY_DEPTH = 256
MAX_BRANCHES = 4096
MAX_EXCLUSIONS = 65536
USAGE = "usage: worker-bundle <branch>/<name> > <bundle>"


def fail(
    message: Annotated[str, "Why no bundle was returned"],
):
    print(f"worker-bundle: {message}", file=sys.stderr)
    sys.exit(2)


def projectHistory(
    arguments: Annotated[list[str], "The fixed Git path for the checked user project"],
):
    """Write bounded recent first-parent histories of every trusted project branch"""
    ## Step 1. List a bounded number of local branch tips from the checked project
    if (len(arguments) != 1):
        print("worker-bundle-history: the Git path is required", file=sys.stderr)
        return 2
    (_git_,) = arguments
    _base_ = [_git_, "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
    _listing_ = subprocess.run(
        [*_base_, "for-each-ref", f"--count={MAX_BRANCHES + 1}", "--format=%(objectname)", "refs/heads/"],
        capture_output=True,
        text=True,
        check=False,
    )
    if (_listing_.returncode != 0):
        print("worker-bundle-history: branch-list-failed", file=sys.stderr)
        return 2
    _tips_ = _listing_.stdout.splitlines()
    if (len(_tips_) > MAX_BRANCHES):
        print(f"worker-bundle-history: more-than-{MAX_BRANCHES}-branches", file=sys.stderr)
        return 2
    if not all(OBJECT.fullmatch(_tip_) for _tip_ in _tips_):
        print("worker-bundle-history: project-tip-invalid", file=sys.stderr)
        return 2

    ## Step 2. Collect each tip's recent first-parent commits, deduplicated under one total bound
    _exclusions_ = set()
    for _tip_ in dict.fromkeys(_tips_):
        _history_ = subprocess.run(
            [*_base_, "rev-list", "--first-parent", f"--max-count={HISTORY_DEPTH}", _tip_],
            capture_output=True,
            text=True,
            check=False,
        )
        _objects_ = _history_.stdout.splitlines()
        if (_history_.returncode != 0) or not all(OBJECT.fullmatch(_object_) for _object_ in _objects_):
            print("worker-bundle-history: project-history-invalid", file=sys.stderr)
            return 2
        _exclusions_.update(_objects_)
        if (len(_exclusions_) > MAX_EXCLUSIONS):
            print(f"worker-bundle-history: more-than-{MAX_EXCLUSIONS}-commits", file=sys.stderr)
            return 2

    ## Step 3. The broker validates this bounded list before forwarding it to the worker sandbox
    if _exclusions_:
        print("\n".join(sorted(_exclusions_)))
    return 0


def create(
    arguments: Annotated[list[str], "The fixed Git path and exact worker ref"],
):
    """Filter trusted project commits through the worker, then stream its bundle"""
    ## Step 1. Check the broker-owned arguments and bounded standard-input candidates
    if (len(arguments) != 2):
        print("worker-bundle-create: the Git path and worker ref are required", file=sys.stderr)
        return 2
    _git_, _reference_ = arguments
    if not re.fullmatch(r"worker/[A-Za-z0-9][A-Za-z0-9._-]{0,47}/[A-Za-z0-9][A-Za-z0-9._-]{0,47}", _reference_):
        print("worker-bundle-create: target-ref-invalid", file=sys.stderr)
        return 2
    try:
        _candidates_ = list(dict.fromkeys(_line_.decode().strip() for _line_ in sys.stdin.buffer))
    except UnicodeDecodeError:
        print("worker-bundle-create: project-history-invalid", file=sys.stderr)
        return 2
    if (len(_candidates_) > MAX_EXCLUSIONS) or not _candidates_ or not all(OBJECT.fullmatch(_object_) for _object_ in _candidates_):
        print("worker-bundle-create: project-history-invalid", file=sys.stderr)
        return 2

    ## Step 2. Disable repository-controlled helpers and keep packing within the bundle scope's memory limit
    _base_ = [
        _git_,
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "pack.threads=1",
        "-c",
        "pack.windowMemory=32m",
        "-c",
        "pack.deltaCacheSize=16m",
    ]
    _target_ = subprocess.run(
        [*_base_, "rev-parse", "--verify", "--quiet", f"{_reference_}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if (_target_.returncode != 0):
        print(f"worker-bundle-create: target-ref-missing:{_reference_}", file=sys.stderr)
        return 3

    ## Step 3. One batch check keeps only trusted project commits this worker actually has
    _query_ = "".join(f"{_object_}\n" for _object_ in _candidates_).encode()
    _inspection_ = subprocess.run(
        [*_base_, "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        input=_query_,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    try:
        _answers_ = _inspection_.stdout.decode().splitlines()
    except UnicodeDecodeError:
        _answers_ = []
    if (_inspection_.returncode != 0) or (len(_answers_) != len(_candidates_)):
        print("worker-bundle-create: project-history-check-failed", file=sys.stderr)
        return 2
    _exclusions_ = []
    for _candidate_, _answer_ in zip(_candidates_, _answers_):
        if (_answer_ == f"{_candidate_} commit"):
            _exclusions_.append(_candidate_)
        elif (_answer_ != f"{_candidate_} missing"):
            print("worker-bundle-create: project-history-check-failed", file=sys.stderr)
            return 2
    if not _exclusions_:
        print("worker-bundle-create: no-shared-project-commit", file=sys.stderr)
        return 4

    ## Step 4. Standard input avoids an argument limit while Git streams bundle bytes directly
    _revisions_ = f"{_reference_}\n" + "".join(f"^{_object_}\n" for _object_ in _exclusions_)
    _bundle_ = subprocess.run(
        [*_base_, "bundle", "create", "-", "--stdin"],
        input=_revisions_.encode(),
        check=False,
    )
    return _bundle_.returncode


def main():
    ## Step 1. Internal forms are fixed commands of the broker's checked Git sandboxes
    _arguments_ = sys.argv[1:]
    if _arguments_ and (_arguments_[0] == "--create"):
        sys.exit(create(_arguments_[1:]))
    if _arguments_ and (_arguments_[0] == "--project-history"):
        sys.exit(projectHistory(_arguments_[1:]))

    ## Step 2. Check the one worker identity and derive the only ref it may request
    if (len(_arguments_) != 1):
        fail(USAGE)
    _names_ = _arguments_[0].split("/")
    if (len(_names_) != 2) or not all(NAME.fullmatch(_name_) for _name_ in _names_):
        fail("the worker is <branch>/<name>, each 1 to 48 letters, digits, '.', '_' or '-'")
    _branch_, _name_ = _names_
    _reference_ = f"worker/{_branch_}/{_name_}"

    ## Step 3. Send the closed request with this command's output descriptor
    _path_ = os.environ.get("WORKER_QUEUE_SOCKET")
    if not _path_:
        fail("this is not a worker sandbox with a broker; nothing was bundled")
    _request_ = {
        "mode": "worker-bundle",
        "command": [_branch_, _name_, _reference_],
        "folder": "/",
        "environment": {},
    }
    _body_ = json.dumps(_request_).encode()
    _message_ = struct.pack(">I", len(_body_)) + _body_
    _connection_ = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _connection_.connect(_path_)
    except OSError as _error_:
        fail(f"the broker of this sandbox does not answer ({_error_}); nothing was bundled")
    _sent_ = socket.send_fds(_connection_, [_message_[:32768]], [0, 1, 2])
    if (_sent_ < len(_message_)):
        _connection_.sendall(_message_[_sent_:])

    ## Step 4. Report the broker's one answer after it has streamed the bundle
    _answer_ = b""
    while not _answer_.endswith(b"\n"):
        _part_ = _connection_.recv(65536)
        if not _part_:
            fail("the broker went away before the bundle ended")
        _answer_ += _part_
    try:
        _result_ = json.loads(_answer_.decode())
    except (UnicodeDecodeError, ValueError):
        fail("the broker returned no valid answer")
    if ("refused" in _result_):
        fail(f"refused: {_result_['refused']}")
    if ("bundle" not in _result_):
        fail("the broker returned no bundle result")


if (__name__ == "__main__"):
    main()
