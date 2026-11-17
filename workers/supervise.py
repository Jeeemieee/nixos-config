# Keep the interactive terminal while a pi worker replaces its sandbox once after approval
import fcntl
import json
import os
import select
import shlex
import shutil
import socket
import sys
import time
from typing import Annotated


def recovery(
    project: Annotated[str, "The user's project folder"],
    branch: Annotated[str, "The worker's branch"],
    name: Annotated[str, "The worker's name"],
):
    print(f"automatic continuation failed; continue the saved chat with: cd {shlex.quote(project)} && pi --branch {branch} --name {name} -c", file=sys.stderr)


MAX_ACKNOWLEDGEMENT_BYTES = 4096
MAX_ACKNOWLEDGEMENT_CONNECTIONS = 16
ACKNOWLEDGEMENT_READ_SECONDS = 0.2
ACKNOWLEDGEMENT_POLL_SECONDS = 0.05


def continuationListener(
    control: Annotated[str, "The trusted host control directory"],
    nonce: Annotated[str, "The continuation generation expected by the supervisor"],
):
    """Create the bounded acknowledgement channel only for a resumed continuation"""
    if not nonce:
        return None
    _path_ = os.path.join(control, "started")
    try:
        os.unlink(_path_)
    except FileNotFoundError:
        pass
    _listener_ = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _listener_.bind(_path_)
        os.chmod(_path_, 0o600)
        _listener_.listen(MAX_ACKNOWLEDGEMENT_CONNECTIONS)
        _listener_.setblocking(False)
        return _listener_
    except OSError:
        _listener_.close()
        try:
            os.unlink(_path_)
        except FileNotFoundError:
            pass
        raise


def waitForChild(
    child: Annotated[int, "The supervised child process"],
    listener: Annotated[socket.socket | None, "The bounded continuation acknowledgement listener"],
    nonce: Annotated[str, "The one acknowledgement value that counts"],
):
    """Wait for the child while bounded nonblocking acknowledgement connections are checked"""
    if (listener is None):
        _, _status_ = os.waitpid(child, 0)
        return _status_, False

    _expected_ = f"{nonce}\n".encode()
    _connections_ = {}
    _matched_ = False
    _endedStatus_ = None
    _exitPolls_ = 0
    _path_ = listener.getsockname()
    try:
        while True:
            ## Step 1. Close idle connections after the short per-connection deadline
            _now_ = time.monotonic()
            for _connection_, (_data_, _deadline_) in list(_connections_.items()):
                if (_now_ >= _deadline_):
                    _connection_.close()
                    del _connections_[_connection_]

            ## Step 2. Handle one bounded nonblocking batch, then return immediately if the child ended
            _readable_, _, _ = select.select([listener, *_connections_], [], [], ACKNOWLEDGEMENT_POLL_SECONDS)
            if (listener in _readable_):
                _readable_.remove(listener)
                for _ in range(MAX_ACKNOWLEDGEMENT_CONNECTIONS):
                    try:
                        _connection_, _ = listener.accept()
                    except BlockingIOError:
                        break
                    _connection_.setblocking(False)
                    if _matched_ or (len(_connections_) >= MAX_ACKNOWLEDGEMENT_CONNECTIONS):
                        _connection_.close()
                    else:
                        _connections_[_connection_] = [bytearray(), time.monotonic() + ACKNOWLEDGEMENT_READ_SECONDS]

            for _connection_ in _readable_:
                _state_ = _connections_.get(_connection_)
                if (_state_ is None):
                    continue
                _data_, _ = _state_
                try:
                    _piece_ = _connection_.recv(MAX_ACKNOWLEDGEMENT_BYTES - len(_data_))
                except BlockingIOError:
                    continue
                if _piece_:
                    _data_.extend(_piece_)
                    if not _matched_ and (bytes(_data_) == _expected_):
                        _matched_ = True
                        _connection_.close()
                        del _connections_[_connection_]
                    elif (b"\n" in _data_) or (len(_data_) >= MAX_ACKNOWLEDGEMENT_BYTES):
                        _connection_.close()
                        del _connections_[_connection_]
                else:
                    _connection_.close()
                    del _connections_[_connection_]

            # Two final bounded polls accept and read data already queued at exit; idle peers add at most two poll intervals
            if (_endedStatus_ is not None):
                _exitPolls_ -= 1
                if (_exitPolls_ == 0):
                    return _endedStatus_, _matched_
            else:
                _finished_, _status_ = os.waitpid(child, os.WNOHANG)
                if _finished_:
                    _endedStatus_ = _status_
                    _exitPolls_ = 2
    finally:
        ## Step 3. The endpoint and every connection end with this supervised session
        for _connection_ in _connections_:
            _connection_.close()
        listener.close()
        try:
            os.unlink(_path_)
        except FileNotFoundError:
            pass


def exitCode(
    status: Annotated[int, "A waitpid status"],
):
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 2


def main():
    ## Step 1. Separate fixed supervision data, restart arguments and the child command
    if (len(sys.argv) < 10):
        print("worker-supervise: incomplete invocation", file=sys.stderr)
        sys.exit(2)
    _control_, _lock_, _unit_, _launcher_, _project_, _branch_, _name_ = sys.argv[1:8]
    try:
        _count_ = int(sys.argv[8])
    except ValueError:
        print("worker-supervise: invalid restart argument count", file=sys.stderr)
        sys.exit(2)
    _argumentsEnd_ = 9 + _count_
    if (_argumentsEnd_ >= len(sys.argv)) or (sys.argv[_argumentsEnd_] != "--"):
        print("worker-supervise: invalid command boundary", file=sys.stderr)
        sys.exit(2)
    _restartArguments_ = sys.argv[9:_argumentsEnd_]
    _command_ = sys.argv[_argumentsEnd_ + 1 :]
    if not _command_:
        print("worker-supervise: no child command", file=sys.stderr)
        sys.exit(2)

    ## Step 2. Run systemd-run in this terminal, while only its child inherits the launcher's name lock
    _internal_ = os.environ.get("WORKER_INTERNAL_RESTART") == _unit_
    _continuationNonce_ = os.environ.get("WORKER_INTERNAL_RESTART_NONCE", "") if _internal_ else ""
    try:
        _listener_ = continuationListener(_control_, _continuationNonce_)
    except OSError:
        recovery(_project_, _branch_, _name_)
        shutil.rmtree(_control_, ignore_errors=True)
        sys.exit(2)
    _child_ = os.fork()
    if (_child_ == 0):
        os.execvp(_command_[0], _command_)
    for _descriptor_ in (8, 9):
        try:
            os.close(_descriptor_)
        except OSError:
            pass
    _status_, _started_ = waitForChild(_child_, _listener_, _continuationNonce_)
    _code_ = exitCode(_status_)

    ## Step 3. A one-use request re-enters the normal launcher with continuation and a newly acquired name lock
    _request_ = os.path.join(_control_, "restart")
    if os.path.isfile(_request_):
        try:
            _requestDescriptor_ = os.open(_request_, os.O_RDONLY | os.O_NOFOLLOW)
            _requestData_ = json.loads(os.read(_requestDescriptor_, 4096))
            os.close(_requestDescriptor_)
            _requestNonce_ = _requestData_.get("nonce") if isinstance(_requestData_, dict) else None
            if not isinstance(_requestNonce_, str) or (len(_requestNonce_) < 16):
                raise OSError("invalid continuation nonce")
            os.unlink(_request_)
            _descriptor_ = os.open(_lock_, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            fcntl.flock(_descriptor_, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (_descriptor_ != 9):
                os.dup2(_descriptor_, 9, inheritable=True)
                os.close(_descriptor_)
            else:
                os.set_inheritable(9, True)
        except OSError:
            recovery(_project_, _branch_, _name_)
            shutil.rmtree(_control_, ignore_errors=True)
            sys.exit(2)
        shutil.rmtree(_control_, ignore_errors=True)
        _environment_ = os.environ.copy()
        _environment_["WORKER_INTERNAL_RESTART"] = _unit_
        _environment_["WORKER_INTERNAL_RESTART_NONCE"] = _requestNonce_
        os.execve(_launcher_, [_launcher_, *_restartArguments_], _environment_)

    ## Step 4. Recovery belongs only to a continuation that failed before its session started
    shutil.rmtree(_control_, ignore_errors=True)
    if (_code_ != 0) and _internal_ and not _started_:
        recovery(_project_, _branch_, _name_)
    sys.exit(_code_)


if (__name__ == "__main__"):
    main()
