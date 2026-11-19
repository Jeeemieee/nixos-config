# The queue's broker: one per pi sandbox, outside it, as the user (see docs/WORKERS.md)
# It takes requests from `queue` inside the sandbox, waits for a slot, and starts the job in a second sandbox that is built
# from the launcher's own description of the worker's view. Nothing in a request is applied outside that job sandbox:
# the command, the folder and the environment only become arguments after bwrap's own, and this process starts every
# program by a fixed path with its own environment
# It relays no output: the job gets the input and output descriptors of the `queue` client itself
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from typing import Annotated

MODES = ("run", "run-parallel", "timing", "exclusive", "acceptance", "acceptance-all", "status", "worker-read", "worker-bundle")
# The modes whose command is not the request's: the broker takes it from the approval and from the project (see _acceptance)
ACCEPTANCE = ("acceptance", "acceptance-all")
FIELDS = {"mode", "command", "folder", "environment"}
POLL_SECONDS = 0.5
# A name of the environment that can never be read as an option, and the one character that ends a word where words are separated by it
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
WORKER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
NUL = "\0"


class Refused(Exception):
    """A request that is not run, with the reason for the client"""


class Broker:
    def __init__(
        self,
        config: Annotated[dict, "The machine's queue settings, written by the system configuration"],
        arguments: Annotated[argparse.Namespace, "This sandbox's settings, from the launcher"],
    ):
        self.config = config
        self.directory = arguments.dir
        self.unit = arguments.unit
        self.records = arguments.records
        self.recordsLimit = int(arguments.records_limit)
        self.scratch = arguments.scratch
        self.repo = arguments.repo
        self.workersRoot = arguments.workers_root
        self.rolesRoot = arguments.roles_root
        self.identity = json.loads(arguments.identity)
        self.active = 0
        self.counter = 0
        # The requests that wait or run, by their number, for `workers status`: kept in a file beside the view, outside the sandbox
        self.requests = {}
        # Connections whose request has not arrived yet, oldest first
        self.waiting = {}
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(config["maxSlots"])
        self.stopping = threading.Event()
        self.server = None
        # The worker's view and the variables that no request may change, as the launcher wrote them
        with open(os.path.join(self.directory, "view"), "rb") as _file_:
            self.view = [_part_.decode() for _part_ in _file_.read().split(b"\0")[:-1]]
        with open(os.path.join(self.directory, "fixed-env"), "rb") as _file_:
            _parts_ = [_part_.decode() for _part_ in _file_.read().split(b"\0")[:-1]]
        self.fixed = list(zip(_parts_[0::2], _parts_[1::2]))

    def serve(self):
        """Accept requests until this service is stopped"""
        _path_ = os.path.join(self.directory, "socket", "queue.sock")
        if os.path.exists(_path_):
            os.unlink(_path_)
        _server_ = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server = _server_
        signal.signal(signal.SIGTERM, self._stop)
        _server_.bind(_path_)
        _server_.listen(16)
        while not self.stopping.is_set():
            try:
                _connection_, _ = _server_.accept()
            except OSError:
                if self.stopping.is_set():
                    break
                raise
            # A client that connects and sends nothing must not keep the broker busy: each request has a time limit to arrive,
            # and when too many connections are open without one, the oldest is closed to make room for the new
            _connection_.settimeout(self.config["requestSeconds"])
            with self.lock:
                while (len(self.waiting) >= self.config["maxConnections"]):
                    _oldest_ = next(iter(self.waiting))
                    del self.waiting[_oldest_]
                    self._reply(_oldest_, {"refused": "too many connections of this sandbox were open without a request; this one was closed"})
                    try:
                        _oldest_.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        # It closed by itself meanwhile
                        pass
                self.waiting[_connection_] = True
            threading.Thread(target=self._handle, args=(_connection_,), daemon=False).start()

    def _stop(
        self,
        _signal: Annotated[int, "The signal that asks the broker to stop"],
        _frame: Annotated[object, "The interrupted frame"],
    ):
        """Stop accepting requests; non-daemon request threads finish their stopped-job records"""
        self.stopping.set()
        if self.server is not None:
            self.server.close()

    def _handle(
        self,
        connection: Annotated[socket.socket, "One client; one request"],
    ):
        _descriptors_ = []
        try:
            ## Step 1. Read and check the one request, within its time limit
            try:
                _request_, _descriptors_ = self._receive(connection)
            except socket.timeout:
                raise Refused(f"no complete request arrived within {self.config['requestSeconds']} seconds")
            finally:
                with self.lock:
                    self.waiting.pop(connection, None)
            connection.settimeout(None)
            if (_request_["mode"] == "status"):
                self._reply(connection, {"status": self._status()})
                return

            ## Step 2. Count reads and jobs against this sandbox's limit of waiting and running requests
            with self.lock:
                if (self.active >= self.config["maxRequests"]):
                    raise Refused(f"this sandbox already has {self.active} requests waiting or running, which is the limit")
                self.active += 1
            _number_ = None
            try:
                if (_request_["mode"] == "worker-read"):
                    self._reply(connection, {"read": self._workerRead(_request_, _descriptors_[1])})
                    return
                if (_request_["mode"] == "worker-bundle"):
                    self._reply(connection, {"bundle": self._workerBundle(_request_, _descriptors_[1])})
                    return
                with self.lock:
                    self.counter += 1
                    _number_ = self.counter
                    self.requests[_number_] = {"mode": _request_["mode"], "state": "waiting", "since": int(time.time()), "command": " ".join(_request_["command"])[:4096]}
                    self._publish()
                _answer_ = self._run(connection, _request_, _descriptors_, _number_)
            finally:
                with self.lock:
                    self.active -= 1
                    if (_number_ is not None):
                        del self.requests[_number_]
                        self._publish()
            self._reply(connection, _answer_)
        except Refused as _refusal_:
            self._reply(connection, {"refused": str(_refusal_)})
        except Exception as _error_:
            # Whatever else goes wrong before a job starts is answered too, never left without a word
            self._reply(connection, {"refused": f"the broker could not handle the request: {_error_!r}"})
        finally:
            for _descriptor_ in _descriptors_:
                os.close(_descriptor_)
            connection.close()

    def _receive(
        self,
        connection: Annotated[socket.socket, "The client's connection"],
    ):
        """One request: a length, then that many bytes of JSON, with exactly three descriptors beside the first part"""
        _limit_ = self.config["maxRequestBytes"]
        # One time limit for the whole request, in however many pieces it arrives
        _deadline_ = time.monotonic() + self.config["requestSeconds"]
        _data_, _descriptors_, _, _ = socket.recv_fds(connection, 65536, 8)
        try:
            if (len(_descriptors_) != 3) or (len(_data_) < 4):
                raise Refused("a request carries its length and exactly three descriptors: input, output and errors")
            (_length_,) = struct.unpack(">I", _data_[:4])
            if (_length_ > _limit_):
                raise Refused(f"the request is larger than {_limit_} bytes")
            _body_ = _data_[4:]
            while (len(_body_) < _length_):
                _left_ = _deadline_ - time.monotonic()
                if (_left_ <= 0):
                    raise socket.timeout()
                connection.settimeout(_left_)
                _more_ = connection.recv(_length_ - len(_body_))
                if not _more_:
                    raise Refused("the request ended before its announced length")
                _body_ += _more_
            try:
                _request_ = json.loads(_body_.decode())
            except (ValueError, RecursionError):
                # RecursionError: lists nested deeper than the reader goes
                raise Refused("the request is not JSON")

            # A closed format: exactly these fields, of exactly these kinds
            if not isinstance(_request_, dict) or (set(_request_) != FIELDS):
                raise Refused(f"a request has exactly the fields {', '.join(sorted(FIELDS))}")
            _command_, _environment_ = _request_["command"], _request_["environment"]
            if (_request_["mode"] not in MODES):
                raise Refused(f"unknown mode; the modes are {', '.join(MODES)}")
            if not isinstance(_command_, list) or not all(isinstance(_word_, str) for _word_ in _command_):
                raise Refused("the command is a list of strings")
            if not isinstance(_request_["folder"], str) or not _request_["folder"].startswith("/"):
                raise Refused("the folder is an absolute path")
            if not isinstance(_environment_, dict) or not all(isinstance(_key_, str) and isinstance(_value_, str) for _key_, _value_ in _environment_.items()):
                raise Refused("the environment maps names to strings")
            # No part of a request may become an option of the job's sandbox. The environment reaches bwrap as words separated by
            # NUL characters, so a NUL inside a word would start a new one; and a name that could be an option is no name
            for _key_ in _environment_:
                if not NAME.fullmatch(_key_):
                    raise Refused(f"'{_key_[:40]}' is not a name of the environment: letters, digits and '_', not starting with a digit".replace(NUL, "<NUL>"))
            _texts_ = (*_environment_.values(), *_command_, _request_["folder"])
            if any(NUL in _text_ for _text_ in _texts_):
                raise Refused("a value of the environment, a word of the command or the folder holds a NUL character")
            # JSON can name half of a surrogate pair, which is no character and cannot be handed to a program
            try:
                for _text_ in _texts_:
                    _text_.encode()
            except UnicodeEncodeError:
                raise Refused("a value of the environment, a word of the command or the folder is not valid Unicode")
            if (_request_["mode"] in ACCEPTANCE):
                if _command_:
                    raise Refused("an acceptance run takes no command: what it runs is the approved tests, by the project's own command")
            elif (_request_["mode"] != "status") and not _command_:
                raise Refused("there is no command to run")
            return _request_, _descriptors_
        except BaseException:
            # Whatever the failure, the client's descriptors are closed here: the caller never got them
            for _descriptor_ in _descriptors_:
                os.close(_descriptor_)
            raise

    def _reply(
        self,
        connection: Annotated[socket.socket, "The client's connection"],
        answer: Annotated[dict, "The one answer to a request"],
    ):
        try:
            connection.sendall(json.dumps(answer).encode() + b"\n")
        except OSError:
            # The client is gone; there is nobody to tell
            pass

    def _gone(
        self,
        connection: Annotated[socket.socket, "The client's connection"],
    ):
        """Whether the client closed its end: it sends nothing after its request, so readable means closed"""
        _readable_, _, _ = select.select([connection], [], [], 0)
        return bool(_readable_)

    def _projectExclusions(self):
        """Read bounded recent branch histories from this worker identity's trusted user project"""
        ## Step 1. Read the launcher-owned project path beside this project's role records
        if not self.rolesRoot:
            raise Refused("this manager has no trusted project state")
        _main_ = os.path.join(os.path.dirname(self.rolesRoot), "main")
        try:
            _descriptor_ = os.open(_main_, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                _status_ = os.fstat(_descriptor_)
                _data_ = os.read(_descriptor_, 4097)
            finally:
                os.close(_descriptor_)
        except OSError:
            raise Refused("the trusted path of this manager's project could not be read")
        if not stat.S_ISREG(_status_.st_mode) or (len(_data_) > 4096):
            raise Refused("the trusted path of this manager's project is not one bounded regular file")
        try:
            _project_ = _data_.decode().removesuffix("\n")
        except UnicodeDecodeError:
            raise Refused("the trusted path of this manager's project is not valid Unicode")
        if not _project_.startswith("/") or ("\n" in _project_) or (os.path.basename(_project_) != self.identity.get("project")):
            raise Refused("the trusted path does not name this manager's project")

        ## Step 2. Ask that repository for bounded recent branch histories inside its own checked sandbox
        _projectPath_ = _project_.lstrip("/")
        _sandbox_ = [
            *self.config["openChecked"],
            self.config["bwrap"],
            "--unshare-all",
            "--die-with-parent",
            "--ro-bind",
            "/nix/store",
            "/nix/store",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--ro-bind-checked",
            "/",
            _projectPath_,
            "/project",
            "--chdir",
            "/project",
            "--clearenv",
            "--",
            *self.config["workerBundleHistory"],
            self.config["git"],
        ]
        try:
            _listing_ = subprocess.run(
                _sandbox_,
                cwd="/",
                capture_output=True,
                text=True,
                timeout=self.config["requestSeconds"],
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise Refused("the recent branch histories of the user's project could not be read")
        if (_listing_.returncode != 0):
            raise Refused("the recent branch histories of the user's project could not be read")
        _lines_ = _listing_.stdout.splitlines()
        if (len(_lines_) > 65536):
            raise Refused("the user's project returned too many recent branch commits")
        _exclusions_ = set()
        for _object_ in _lines_:
            if (len(_object_) not in (40, 64)) or any(_letter_ not in "0123456789abcdef" for _letter_ in _object_):
                raise Refused("the user's project returned a malformed branch history")
            _exclusions_.add(_object_)
        if not _exclusions_:
            raise Refused("the user's project has no branch history to exclude from the bundle")
        return sorted(_exclusions_)

    def _workerBundle(
        self,
        request: Annotated[dict, "A checked manager bundle request"],
        output: Annotated[int, "The client's output descriptor"],
    ):
        """Stream one worker ref, excluding trusted project history the worker has"""
        ## Step 1. Check the authority and the one exact target ref
        if (self.identity.get("role") != "manager"):
            raise Refused("only a manager receives another worker's bundle")
        if not self.workersRoot or not self.rolesRoot:
            raise Refused("this manager has no project worker root")
        if (request["environment"] or (request["folder"] != "/")):
            raise Refused("a worker-bundle request has no environment and uses the root folder")
        if (len(request["command"]) != 3):
            raise Refused("a worker-bundle request is exactly its branch, worker name and ref")
        _branch_, _name_, _reference_ = request["command"]
        if not WORKER_NAME.fullmatch(_branch_) or not WORKER_NAME.fullmatch(_name_):
            raise Refused("the worker is <branch>/<name>, each a checked worker name")
        _expected_ = f"worker/{_branch_}/{_name_}"
        if (_reference_ != _expected_):
            raise Refused(f"the requested ref is {_expected_}, never another ref")

        ## Step 2. Require a recorded worker of this project and read exclusions only from the user project
        _roleDescriptor_ = None
        try:
            _roleDescriptor_ = self._openBelow(self.rolesRoot, [_branch_, _name_])
            _roleStatus_ = os.fstat(_roleDescriptor_)
            _role_ = os.read(_roleDescriptor_, 64).decode(errors="replace").strip()
        except Refused:
            _roleStatus_, _role_ = None, ""
        finally:
            if (_roleDescriptor_ is not None):
                os.close(_roleDescriptor_)
        if ((_roleStatus_ is None) or not stat.S_ISREG(_roleStatus_.st_mode) or (_role_ not in ("implementer", "reviewer", "deep-reviewer", "manager"))):
            raise Refused(f"there is no worker {self.identity['project']}/{_branch_}/{_name_}")
        _exclusions_ = self._projectExclusions()

        ## Step 3. Run the fixed creator with the checked repository descriptor, no network and finite resources
        _repoParts_ = [_branch_, _name_, "repo"]
        _repo_ = os.path.join(self.workersRoot, *_repoParts_)
        _unit_ = f"worker-bundle-{os.getpid()}-{threading.get_native_id()}-{time.monotonic_ns()}"
        _sandbox_ = [
            self.config["systemdRun"],
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            "--expand-environment=no",
            f"--unit={_unit_}",
            "--slice=workers-jobs.slice",
            "-p",
            "MemoryMax=128M",
            "-p",
            "MemorySwapMax=0",
            "-p",
            f"RuntimeMaxSec={self.config['requestSeconds']}",
            "-p",
            "TimeoutStopSec=5",
            "--",
            *self.config["openChecked"],
            self.config["bwrap"],
            "--unshare-all",
            "--die-with-parent",
            "--ro-bind",
            "/nix/store",
            "/nix/store",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--ro-bind-checked",
            self.workersRoot,
            "/".join(_repoParts_),
            _repo_,
            "--chdir",
            _repo_,
            "--clearenv",
            "--",
            *self.config["workerBundleCreate"],
            self.config["git"],
            _reference_,
        ]
        _process_ = subprocess.Popen(_sandbox_, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _candidateInput_ = ("\n".join(_exclusions_) + "\n").encode()
        self._output(_process_.stdin.fileno(), _candidateInput_)
        _process_.stdin.close()

        ## Step 4. Relay bounded pieces immediately, retaining only a short diagnostic from errors
        _bytes_ = 0
        _error_ = bytearray()
        _deadline_ = time.monotonic() + self.config["requestSeconds"]
        _streams_ = {_process_.stdout.fileno(): "output", _process_.stderr.fileno(): "error"}
        _refusal_ = None
        while _streams_ and (_refusal_ is None):
            _left_ = _deadline_ - time.monotonic()
            if (_left_ <= 0):
                _refusal_ = f"the bundle did not finish within {self.config['requestSeconds']} seconds"
                break
            _readable_, _, _ = select.select(list(_streams_), [], [], _left_)
            if not _readable_:
                _refusal_ = f"the bundle did not finish within {self.config['requestSeconds']} seconds"
                break
            for _descriptor_ in _readable_:
                _chunk_ = os.read(_descriptor_, 65536)
                if not _chunk_:
                    del _streams_[_descriptor_]
                    continue
                if (_streams_[_descriptor_] == "error"):
                    _room_ = 8192 - len(_error_)
                    if (_room_ > 0):
                        _error_.extend(_chunk_[:_room_])
                    continue
                _limit_ = self.config["maxBundleBytes"]
                _room_ = _limit_ - _bytes_
                if (_room_ > 0):
                    _part_ = _chunk_[:_room_]
                    self._output(output, _part_)
                    _bytes_ += len(_part_)
                if (len(_chunk_) > _room_):
                    _refusal_ = f"the bundle is larger than {_limit_} bytes, the configured limit"
                    break

        ## Step 5. Stop an over-limit or late scope, then classify the creator's bounded result
        if (_refusal_ is not None):
            subprocess.run(
                [self.config["systemctl"], "--user", "kill", "--kill-whom=all", f"{_unit_}.scope"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            _process_.wait()
            raise Refused(_refusal_)
        try:
            _status_ = _process_.wait(timeout=max(0.1, _deadline_ - time.monotonic()))
        except subprocess.TimeoutExpired:
            subprocess.run(
                [self.config["systemctl"], "--user", "kill", "--kill-whom=all", f"{_unit_}.scope"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            _process_.wait()
            raise Refused(f"the bundle did not finish within {self.config['requestSeconds']} seconds")
        _errorText_ = _error_.decode(errors="replace")
        if (_status_ == 3):
            raise Refused(f"the worker copy has no committed ref {_reference_}")
        if (_status_ == 4) and ("no-shared-project-commit" in _errorText_):
            raise Refused("the worker's copy shares no commit with the user's project")
        if (_status_ != 0):
            raise Refused("git could not create the bundle safely")
        return {"bytes": _bytes_, "ref": _reference_}

    def _workerRead(
        self,
        request: Annotated[dict, "A checked manager read request"],
        output: Annotated[int, "The client's output descriptor"],
    ):
        """List or read one managed worker path of this project without adding a mount"""
        ## Step 1. Check the authority and the closed request
        if (self.identity.get("role") != "manager"):
            raise Refused("only a manager reads other workers through worker-read")
        if not self.workersRoot or not self.rolesRoot:
            raise Refused("this manager has no project worker root")
        if (request["environment"] or (request["folder"] != "/")):
            raise Refused("a worker-read request has no environment and uses the root folder")

        ## Step 2. List the workers recorded for this project at request time
        if (request["command"] == ["workers"]):
            _lines_ = []
            _size_ = 0
            _rolesDescriptor_ = self._openBelow(self.rolesRoot, [])
            try:
                with os.scandir(_rolesDescriptor_) as _branches_:
                    for _branchEntry_ in _branches_:
                        if (not WORKER_NAME.fullmatch(_branchEntry_.name) or not _branchEntry_.is_dir(follow_symlinks=False)):
                            continue
                        try:
                            _branchDescriptor_ = self._openBelow(self.rolesRoot, [_branchEntry_.name])
                        except Refused:
                            continue
                        try:
                            with os.scandir(_branchDescriptor_) as _names_:
                                for _nameEntry_ in _names_:
                                    if (not WORKER_NAME.fullmatch(_nameEntry_.name) or not _nameEntry_.is_file(follow_symlinks=False)):
                                        continue
                                    try:
                                        _roleDescriptor_ = self._openBelow(self.rolesRoot, [_branchEntry_.name, _nameEntry_.name])
                                        _roleStatus_ = os.fstat(_roleDescriptor_)
                                        _role_ = os.read(_roleDescriptor_, 64).decode(errors="replace").strip()
                                        os.close(_roleDescriptor_)
                                    except Refused:
                                        continue
                                    if stat.S_ISREG(_roleStatus_.st_mode) and (_role_ in ("implementer", "reviewer", "deep-reviewer", "manager")):
                                        _line_ = (json.dumps(f"{_branchEntry_.name}/{_nameEntry_.name}", ensure_ascii=True) + "\n").encode()
                                        _size_ += len(_line_)
                                        if (_size_ > self.config["maxReadBytes"]):
                                            raise Refused(f"the worker listing is larger than {self.config['maxReadBytes']} bytes")
                                        _lines_.append(_line_)
                        finally:
                            os.close(_branchDescriptor_)
            finally:
                os.close(_rolesDescriptor_)
            _data_ = b"".join(sorted(_lines_))
            self._output(output, _data_)
            return {"bytes": len(_data_), "more": False}

        ## Step 3. Check one worker, root, path and read form
        if (len(request["command"]) != 6):
            raise Refused("a worker-read request is a worker listing or exactly its worker, root, path, offset and read mode")
        _branch_, _name_, _part_, _path_, _offsetText_, _readMode_ = request["command"]
        if (not WORKER_NAME.fullmatch(_branch_) or not WORKER_NAME.fullmatch(_name_)):
            raise Refused("the worker is <branch>/<name>, each a checked worker name")
        _roots_ = ("folder", "reports", "records", "repo", "sessions", "scratch")
        if (_part_ not in (*_roots_, "diff", "refs")):
            raise Refused("the root is folder, reports, records, repo, sessions or scratch, or the operation is diff or refs")
        _pathParts_ = _path_.split("/") if _path_ else []
        _shownRoot_ = "repo" if (_part_ == "diff") else _part_
        if (_path_.startswith("/") or any((_item_ in ("", ".", "..")) for _item_ in _pathParts_)):
            raise Refused(f"the path stays below {_shownRoot_}")
        if not _offsetText_.isdigit():
            raise Refused("the offset is a non-negative byte count")
        if (_readMode_ not in ("read", "sha256")):
            raise Refused("the read mode is read or sha256, never write")
        _offset_ = int(_offsetText_)
        if ((_part_ == "refs") and _path_):
            raise Refused("refs takes no path")
        if (_part_ in ("diff", "refs")) and ((_readMode_ != "read") or (_offset_ != 0)):
            raise Refused(f"{_part_} is one bounded result without --sha256 or --offset")

        ## Step 4. Require a recorded worker of this project
        _roleDescriptor_ = None
        try:
            _roleDescriptor_ = self._openBelow(self.rolesRoot, [_branch_, _name_])
            _roleStatus_ = os.fstat(_roleDescriptor_)
            _role_ = os.read(_roleDescriptor_, 64).decode(errors="replace").strip()
        except Refused:
            _roleStatus_, _role_ = None, ""
        finally:
            if (_roleDescriptor_ is not None):
                os.close(_roleDescriptor_)
        if ((_roleStatus_ is None) or not stat.S_ISREG(_roleStatus_.st_mode) or (_role_ not in ("implementer", "reviewer", "deep-reviewer", "manager"))):
            raise Refused(f"there is no worker {self.identity['project']}/{_branch_}/{_name_}")

        ## Step 5. Produce fixed Git views only in a bounded, read-only sandbox
        if (_part_ in ("diff", "refs")):
            _repoParts_ = [_branch_, _name_, "repo"]
            _repo_ = os.path.join(self.workersRoot, *_repoParts_)
            try:
                _repoDescriptor_ = self._openBelow(self.workersRoot, _repoParts_)
                _repoStatus_ = os.fstat(_repoDescriptor_)
                os.close(_repoDescriptor_)
            except Refused:
                raise Refused(f"there is no repository {_repo_} that is reached without a link")
            if not stat.S_ISDIR(_repoStatus_.st_mode):
                raise Refused(f"{_repo_} is not a directory")
            _git_ = [
                self.config["git"],
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "--no-pager",
            ]
            if (_part_ == "diff"):
                _git_ += [
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-color",
                    "--no-renames",
                    "--src-prefix=a/",
                    "--dst-prefix=b/",
                    "--abbrev=7",
                    "--binary",
                    "HEAD",
                    "--",
                    *([_path_] if _path_ else []),
                ]
            else:
                _git_ += ["for-each-ref", "--format=%(objectname) %(refname)"]
            _unit_ = f"worker-read-{os.getpid()}-{threading.get_native_id()}-{time.monotonic_ns()}"
            _sandbox_ = [
                self.config["systemdRun"],
                "--user",
                "--scope",
                "--quiet",
                "--collect",
                "--expand-environment=no",
                f"--unit={_unit_}",
                "--slice=workers-jobs.slice",
                "-p",
                "MemoryMax=128M",
                "-p",
                "MemorySwapMax=0",
                "-p",
                f"RuntimeMaxSec={self.config['requestSeconds']}",
                "-p",
                "TimeoutStopSec=5",
                "--",
                *self.config["openChecked"],
                self.config["bwrap"],
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind",
                "/nix/store",
                "/nix/store",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--ro-bind-checked",
                self.workersRoot,
                "/".join(_repoParts_),
                _repo_,
                "--chdir",
                _repo_,
                "--clearenv",
                "--",
                *_git_,
            ]
            _process_ = subprocess.Popen(_sandbox_, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            _data_ = bytearray()
            _deadline_ = time.monotonic() + self.config["requestSeconds"]
            _refusal_ = None
            while True:
                _left_ = _deadline_ - time.monotonic()
                if (_left_ <= 0):
                    _refusal_ = f"the {_part_} did not finish within {self.config['requestSeconds']} seconds"
                    break
                _readable_, _, _ = select.select([_process_.stdout], [], [], _left_)
                if not _readable_:
                    _refusal_ = f"the {_part_} did not finish within {self.config['requestSeconds']} seconds"
                    break
                _chunk_ = os.read(_process_.stdout.fileno(), min(65536, (self.config["maxReadBytes"] + 1) - len(_data_)))
                if not _chunk_:
                    break
                _data_.extend(_chunk_)
                if (len(_data_) > self.config["maxReadBytes"]):
                    _refusal_ = f"the {_part_} is larger than {self.config['maxReadBytes']} bytes"
                    if (_part_ == "diff"):
                        _refusal_ += "; narrow it to a path"
                    break
            if (_refusal_ is not None):
                subprocess.run([self.config["systemctl"], "--user", "kill", "--kill-whom=all", f"{_unit_}.scope"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _process_.wait()
                raise Refused(_refusal_)
            try:
                _status_ = _process_.wait(timeout=max(0.1, _deadline_ - time.monotonic()))
            except subprocess.TimeoutExpired:
                subprocess.run([self.config["systemctl"], "--user", "kill", "--kill-whom=all", f"{_unit_}.scope"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _process_.wait()
                raise Refused(f"the {_part_} did not finish within {self.config['requestSeconds']} seconds")
            if (_status_ != 0):
                raise Refused(f"git could not produce the {_part_} safely")
            _result_ = bytes(_data_)
            self._output(output, _result_)
            return {"bytes": len(_result_), "more": False}

        ## Step 6. Open one managed path once, without following a link
        if (_part_ == "scratch"):
            _identityBranch_ = self.identity.get("branch")
            _identityName_ = self.identity.get("name")
            if (os.path.basename(self.scratch) != _identityName_) or (os.path.basename(os.path.dirname(self.scratch)) != _identityBranch_):
                raise Refused("this manager has no trusted project scratch root")
            _root_ = os.path.dirname(os.path.dirname(self.scratch))
            _relative_ = [_branch_, _name_, *_pathParts_]
        else:
            _root_ = self.workersRoot
            _relative_ = [_branch_, _name_]
            if (_part_ != "folder"):
                _relative_.append(_part_)
            _relative_ += _pathParts_
        _shown_ = os.path.join(_root_, *_relative_)
        try:
            _descriptor_ = self._openBelow(_root_, _relative_)
        except Refused:
            raise Refused(f"there is no path {_shown_} that is reached without a link")
        try:
            _status_ = os.fstat(_descriptor_)
            if stat.S_ISDIR(_status_.st_mode):
                if (_readMode_ != "read") or (_offset_ != 0):
                    raise Refused("a directory is listed without --sha256 or --offset")
                _lines_ = []
                _size_ = 0
                with os.scandir(_descriptor_) as _entries_:
                    for _entry_ in _entries_:
                        _line_ = (json.dumps(_entry_.name, ensure_ascii=True) + "\n").encode()
                        _size_ += len(_line_)
                        if (_size_ > self.config["maxReadBytes"]):
                            raise Refused(f"the directory listing is larger than {self.config['maxReadBytes']} bytes; name a path inside it")
                        _lines_.append(_line_)
                _data_ = b"".join(sorted(_lines_))
                self._output(output, _data_)
                return {"bytes": len(_data_), "more": False}
            if not stat.S_ISREG(_status_.st_mode):
                raise Refused(f"{_shown_} is not a regular file or directory")
            if (_readMode_ == "sha256"):
                if (_offset_ != 0):
                    raise Refused("--sha256 is used without --offset")
                _digest_ = hashlib.sha256()
                while True:
                    _partData_ = os.read(_descriptor_, 1024 * 1024)
                    if not _partData_:
                        break
                    _digest_.update(_partData_)
                _data_ = (_digest_.hexdigest() + "\n").encode()
                self._output(output, _data_)
                return {"bytes": len(_data_), "more": False}
            if (_offset_ > _status_.st_size):
                raise Refused(f"the offset {_offset_} is beyond the file's {_status_.st_size} bytes")
            os.lseek(_descriptor_, _offset_, os.SEEK_SET)
            _chunks_ = []
            _left_ = self.config["maxReadBytes"]
            while (_left_ > 0):
                _chunk_ = os.read(_descriptor_, _left_)
                if not _chunk_:
                    break
                _chunks_.append(_chunk_)
                _left_ -= len(_chunk_)
            _data_ = b"".join(_chunks_)
            self._output(output, _data_)
            _next_ = _offset_ + len(_data_)
            return {"bytes": len(_data_), "more": _next_ < _status_.st_size, "nextOffset": _next_}
        finally:
            os.close(_descriptor_)

    def _openBelow(
        self,
        root: Annotated[str, "A trusted root outside the sandbox"],
        parts: Annotated[list, "Checked path components below the root"],
    ):
        """Open a path below a root without following a link at any level"""
        _descriptor_ = None
        try:
            _descriptor_ = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            for _index_, _part_ in enumerate(parts):
                _flags_ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
                if (_index_ < (len(parts) - 1)):
                    _flags_ |= os.O_DIRECTORY
                _next_ = os.open(_part_, _flags_, dir_fd=_descriptor_)
                os.close(_descriptor_)
                _descriptor_ = _next_
            return _descriptor_
        except OSError:
            if (_descriptor_ is not None):
                os.close(_descriptor_)
            raise Refused("the path is missing or is reached through a link")

    def _output(
        self,
        descriptor: Annotated[int, "The client's output descriptor"],
        data: Annotated[bytes, "The bounded bytes to write"],
    ):
        """Write all data unless the reader of a pipeline has deliberately gone away"""
        _left_ = memoryview(data)
        try:
            while _left_:
                _written_ = os.write(descriptor, _left_)
                _left_ = _left_[_written_:]
        except BrokenPipeError:
            pass

    def _lock(
        self,
        connection: Annotated[socket.socket, "The client's connection, to give up when it goes away"],
        names: Annotated[list, "Lock files of which one is enough"],
        shared: Annotated[bool, "Shared instead of exclusive"] = False,
    ):
        """Wait for one of the lock files; the kernel drops the lock when this process ends, however it ends"""
        _kind_ = (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB
        while True:
            for _name_ in names:
                _descriptor_ = os.open(os.path.join(self.config["locks"], _name_), os.O_RDONLY)
                try:
                    fcntl.flock(_descriptor_, _kind_)
                    return _descriptor_
                except BlockingIOError:
                    os.close(_descriptor_)
            if self._gone(connection):
                raise Refused("the client went away while waiting")
            time.sleep(POLL_SECONDS)

    def _numbered(
        self,
        prefix: Annotated[str, "slot or parallel"],
    ):
        return sorted(_name_ for _name_ in os.listdir(self.config["locks"]) if _name_.startswith(prefix) and _name_[len(prefix):].isdigit())

    def _run(
        self,
        connection: Annotated[socket.socket, "The client's connection"],
        request: Annotated[dict, "The checked request"],
        descriptors: Annotated[list, "The client's input, output and error descriptors"],
        number: Annotated[int, "This sandbox's running number of the job"],
    ):
        _mode_ = request["mode"]
        _held_ = []
        _reserved_ = False
        _localSlot_ = False
        _queued_ = time.time()
        try:
            ## Step 1. Wait for the slot, as the mode asks
            if (_mode_ == "exclusive"):
                # Block new jobs, then wait until every running job has finished
                _held_.append(self._lock(connection, ["turnstile"]))
                _held_.append(self._lock(connection, ["heavy"]))
                _held_.append(self._lock(connection, ["timing"]))
            elif (_mode_ == "timing"):
                # Queue behind a waiting exclusive job, share the machine with other jobs, one timing job at a time
                _turnstile_ = self._lock(connection, ["turnstile"])
                _held_.append(self._lock(connection, ["heavy"], shared=True))
                os.close(_turnstile_)
                _held_.append(self._lock(connection, ["timing"]))
            else:
                # Wait for this sandbox's allowance before taking any machine-wide token or slot
                while not self.slots.acquire(timeout=POLL_SECONDS):
                    if self._gone(connection):
                        raise Refused("the client went away while waiting for this sandbox's slot allowance")
                _localSlot_ = True
                # A job waiting for the parallel token holds no slot meanwhile
                if (_mode_ == "run-parallel"):
                    _held_.append(self._lock(connection, self._numbered("parallel")))
                _held_.append(self._lock(connection, self._numbered("slot")))
                _turnstile_ = self._lock(connection, ["turnstile"])
                _held_.append(self._lock(connection, ["heavy"], shared=True))
                os.close(_turnstile_)

            ## Step 2. A timing job runs only while everything else of the user is off the timing cores
            if (_mode_ == "timing") and self.config["timingCpus"]:
                self._reserve()
                _reserved_ = True

            ## Step 3. Run the job in its own sandbox and resource group, and record it
            return self._job(connection, request, descriptors, number, _queued_)
        finally:
            if _reserved_:
                self._release()
            for _descriptor_ in _held_:
                os.close(_descriptor_)
            if _localSlot_:
                self.slots.release()

    def _job(
        self,
        connection: Annotated[socket.socket, "The client's connection"],
        request: Annotated[dict, "The checked request"],
        descriptors: Annotated[list, "The client's input, output and error descriptors"],
        number: Annotated[int, "This sandbox's running number of the job"],
        queued: Annotated[float, "When the request arrived"],
    ):
        _mode_ = request["mode"]
        # An acceptance run: the command, the folder and the environment are the tools', not the request's
        _acceptance_ = {}
        if (_mode_ in ACCEPTANCE):
            request, _acceptance_ = self._acceptance(_mode_)
        _started_ = time.time()
        # The time to the microsecond: a worker's next session numbers its jobs from 1 again, and may start within the same second
        _identifier_ = f"{datetime.datetime.now().strftime('%Y%m%dT%H%M%S.%f')}-{number}"
        _unit_ = f"job-{self.unit}-{number}"
        # The kept copy of the output is written inside the job's sandbox; a sandbox without a scratch area keeps none
        _log_ = os.path.join(self.scratch, "runs", _identifier_, "output.log") if self.scratch else ""

        ## Step 1. The record of the start. No job runs without one: if it cannot be written, nothing is run
        # The commit the worker's copy is at, asked from outside every repository with the copy as the remote: nothing in the copy runs
        _record_ = dict(self.identity)
        _record_.update(
            {
                "id": _identifier_,
                "mode": _mode_,
                "command": request["command"],
                "folder": request["folder"],
                "start": datetime.datetime.fromtimestamp(_started_).astimezone().isoformat(timespec="seconds"),
                "waited_s": round(_started_ - queued),
                "output": _log_,
                "commit": self._commit(),
                "state": "started",
            }
        )
        _record_.update(_acceptance_)
        try:
            self._record(_record_)
        except OSError as _error_:
            raise Refused(f"the run could not be recorded ({_error_.strerror}), so nothing was run; a full folder of this worker is the usual reason")

        ## Step 2. The job's sandbox: the launcher's view first, then the request, then what the request may not change
        # The request's environment reaches bwrap through a descriptor, not its command line, which every process on the machine can read
        _environment_ = os.memfd_create("job-environment")
        try:
            for _key_, _value_ in request["environment"].items():
                os.write(_environment_, b"".join(_word_.encode() + b"\0" for _word_ in ("--setenv", _key_, _value_)))
            os.lseek(_environment_, 0, os.SEEK_SET)
            # open-checked opens what the view names inside agent-written places, as it does for the agent's own sandbox
            _sandbox_ = [*self.config["openChecked"], self.config["bwrap"], "--clearenv", *self.view, "--args", str(_environment_)]
            for _key_, _value_ in self.fixed:
                _sandbox_ += ["--setenv", _key_, _value_]
            _sandbox_ += ["--setenv", "WORKER_JOB", _mode_, "--setenv", "QUEUE_RUN_DIR", os.path.dirname(_log_), "--chdir", "/"]
            _sandbox_ += ["--", self.config["jobWrapper"], request["folder"], _log_, "--", *request["command"]]

            ## Step 3. Its resource group: a scope of its own, bound to this broker, in the slice of its mode
            _service_ = f"broker-{self.unit}.service"
            _slice_ = "workers-timing.slice" if (_mode_ == "timing") else "workers-jobs.slice"
            # systemd-run would otherwise rewrite $NAME in the command line it is given, with this broker's own variables
            _scope_ = [self.config["systemdRun"], "--user", "--scope", "--quiet", "--collect", "--expand-environment=no", f"--unit={_unit_}", f"--slice={_slice_}"]
            # Without a description systemd writes the whole command line into the journal, the request's environment with it
            _scope_ += [f"--description=Queued job {number} of {self.unit}"]
            _scope_ += ["-p", f"BindsTo={_service_}", "-p", f"After={_service_}", "-p", "OOMPolicy=continue"]
            # The kernel limits the whole job, including every child; asking for more threads cannot enlarge its share
            if (_mode_ in ("run", *ACCEPTANCE)):
                _scope_ += ["-p", f"CPUQuota={100 * self.config['jobProcessors']}%"]
            _scope_ += ["--"]

            # When memory runs out, a job is stopped before an agent: the job's own command line sets that, before bwrap starts
            _priority_ = [self.config["choom"], "-n", str(self.config["jobOomScoreAdjust"]), "--"]
            # Between the two, in the job's resource group and outside its sandbox: the program that starts the sandbox and, when it
            # has ended, writes down what the group says of the job's memory; the file is beside the view, where no sandbox reaches
            _measure_ = os.path.join(self.directory, f"measured-{number}")
            _process_ = subprocess.Popen(
                _scope_ + _priority_ + [self.config["jobMeasure"], _measure_] + _sandbox_,
                stdin=descriptors[0],
                stdout=descriptors[1],
                stderr=descriptors[2],
                close_fds=True,
                pass_fds=(_environment_,),
            )
        finally:
            os.close(_environment_)

        with self.lock:
            self.requests[number].update({"state": "running", "since": int(_started_), "unit": f"{_unit_}.scope", "slice": _slice_})
            self._publish()

        ## Step 4. Wait for its end. A client that goes away ends its job, and so does the time limit of the job's mode, if the
        # machine has one: by stopping the scope and so everything in it
        _limit_ = self.config["maxRunSeconds"]["run" if (_mode_ in ("run-parallel", *ACCEPTANCE)) else _mode_]
        _stopped_ = False
        _halted_ = False
        _late_ = False
        while (_process_.poll() is None):
            if not _stopped_:
                _late_ = bool(_limit_) and (time.time() - _started_ > _limit_)
                _stopped_ = _late_ or self._gone(connection)
            # The scope may not exist yet when its client goes away the moment the job has its slot: it is stopped as soon as
            # it does. Asked once and no more, the job would then run to its end without a client
            if _stopped_ and not _halted_:
                _halted_ = (subprocess.run([self.config["systemctl"], "--user", "stop", f"{_unit_}.scope"], check=False, stderr=subprocess.DEVNULL).returncode == 0)
            time.sleep(0.2)
        # What the job's resource group said at its end: the highest memory, and the processes that the kernel stopped for memory
        _peak_, _stops_ = self._measured(_measure_)
        _status_ = _process_.returncode if (_process_.returncode >= 0) else (128 - _process_.returncode)
        _stopped_ = _stopped_ or (self.stopping.is_set() and (_status_ != 0))

        ## Step 5. The record of the end: written here, where the worker cannot change it
        del _record_["state"]
        _record_.update(
            {
                "duration_s": round(time.time() - _started_),
                "exit": _status_,
                "stopped": _stopped_,
                "time_limit": _late_,
                **({"memory_peak": _peak_} if _peak_ is not None else {}),
                **({"memory_stops": _stops_} if _stops_ else {}),
                # Asked inside the job's sandbox, so it is the worker's own word; the commit above is not
                "uncommitted_as_reported": self._reported(os.path.join(os.path.dirname(_log_), "uncommitted")) if _log_ else None,
            }
        )
        # The job ran, so the client gets its status whatever happens here; what else there is to say goes beside it
        _notes_ = [f"the job was stopped after {_limit_} seconds, the time limit of '{_mode_}' jobs on this machine"] if _late_ else []
        try:
            self._record(_record_)
        except OSError as _error_:
            _notes_.append(f"the end of this run could not be recorded ({_error_.strerror}); its start is in the records")

        # A successful implementer baseline can be the second half of approval and baseline; the approval program owns that decision
        if (_mode_ == "acceptance") and (_status_ == 0) and not _stopped_ and not _late_:
            _worker_ = f"{self.identity['project']}/{self.identity['branch']}/{self.identity['name']}"
            subprocess.run([*self.config["approve"], "--request-restart", _worker_], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

        _answer_ = {"exit": _status_}
        if _notes_:
            _answer_["note"] = "; ".join(_notes_)
        return _answer_

    def _acceptance(
        self,
        mode: Annotated[str, "acceptance, or acceptance-all for the whole suite in a manager's copy"],
    ):
        """The request that an acceptance run stands for, and what its record says besides: nothing of it is the worker's choice"""
        _role_ = self.identity.get("role")
        if (mode == "acceptance") and (_role_ != "implementer"):
            raise Refused("an acceptance run is an implementer's: the tests that were approved with its intent")
        if (mode == "acceptance-all") and (_role_ != "manager"):
            raise Refused("--all is a manager's: the project's whole suite on the merged result in its copy")
        # Which tests, taken from which commit of the project, run by which command: read from the approval, the form and the
        # project's own workers.toml by the program that owns those records
        _worker_ = f"{self.identity['project']}/{self.identity['branch']}/{self.identity['name']}"
        _asked_ = subprocess.run([*self.config["approve"], "--acceptance", _worker_], capture_output=True, text=True, check=False)
        if (_asked_.returncode != 0):
            raise Refused(_asked_.stderr.strip().removeprefix("workers: ") or "the tests of this worker could not be determined")
        _plan_ = json.loads(_asked_.stdout)
        # Which commit of the copy: the one of the worker's own branch, as that program says, wherever the copy's files stand
        _command_ = [self.config["acceptanceJob"], os.path.join(_plan_["project"], ".git"), _plan_["testsCommit"], self.repo, _plan_["reference"], _plan_["copyCommit"]]
        _command_ += [str(len(_plan_["paths"])), *_plan_["paths"], *_plan_["command"]]
        # Only what the launcher set reaches the tests, and the home: the environment of the `queue` command could change what they do
        _request_ = {"mode": mode, "command": _command_, "folder": self.repo, "environment": {"HOME": os.environ["HOME"]}}
        # The record names the commit that is tested, not the one that happens to be checked out
        _extra_ = {"kind": "acceptance", "list": _plan_["list"], "tests": _plan_["tests"], "listDigest": _plan_["listDigest"], "testsCommit": _plan_["testsCommit"], "commit": _plan_["copyCommit"]}
        return _request_, _extra_

    def _measured(
        self,
        path: Annotated[str, "The file that the job's first program outside its sandbox wrote at the job's end"],
    ):
        """The job's highest memory and its processes stopped for memory; nothing for a job that was stopped before it could say"""
        try:
            with open(path) as _file_:
                _words_ = _file_.read(200).split()
            os.unlink(path)
            return int(_words_[0]), int(_words_[1])
        except (OSError, ValueError, IndexError):
            return None, 0

    def _publish(self):
        """Write down which requests wait and run, as a new file put in place by a rename; called with the lock held"""
        _path_ = os.path.join(self.directory, "state.json")
        with open(_path_ + ".new", "w") as _file_:
            json.dump({"requests": list(self.requests.values())}, _file_)
        os.replace(_path_ + ".new", _path_)

    def _record(
        self,
        record: Annotated[dict, "One line of this sandbox's run records"],
    ):
        with self.lock:
            # An ordinary session's records are in the home and have no dataset to limit them: one older file is kept
            if self.recordsLimit and os.path.exists(self.records) and (os.path.getsize(self.records) > self.recordsLimit):
                os.replace(self.records, self.records + ".1")
            with open(self.records, "a") as _file_:
                _file_.write(json.dumps(record) + "\n")

    def _commit(self):
        """The commit that HEAD of the worker's copy names, or nothing for a sandbox without a copy"""
        if not self.repo:
            return None
        try:
            _answer_ = subprocess.run(
                [self.config["git"], "ls-remote", f"file://{self.repo}", "HEAD"], cwd="/", capture_output=True, text=True, timeout=20, check=True
            ).stdout.split()
        except (subprocess.SubprocessError, OSError):
            return None
        return _answer_[0] if _answer_ and (len(_answer_[0]) in (40, 64)) and all(_letter_ in "0123456789abcdef" for _letter_ in _answer_[0]) else None

    def _reported(
        self,
        path: Annotated[str, "A file the job's sandbox wrote"],
    ):
        """A short word from a file an agent could have written: read as data, with a size limit, and only one of two values"""
        try:
            _descriptor_ = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            _word_ = os.read(_descriptor_, 8).decode(errors="replace").strip()
            os.close(_descriptor_)
        except OSError:
            return None
        return _word_ if (_word_ in ("yes", "no")) else None

    def _slices(self):
        """What is moved off the timing cores: every top-level slice of the user's systemd that exists now, and the slices in workers.slice but the timing one"""
        _listing_ = subprocess.run(
            [self.config["systemctl"], "--user", "list-units", "--type=slice", "--all", "--no-legend", "--plain"], check=True, capture_output=True, text=True
        ).stdout
        _names_ = [_line_.split()[0] for _line_ in _listing_.splitlines() if _line_.split()]
        _found_ = []
        for _name_ in _names_:
            _stem_ = _name_[: -len(".slice")]
            if (_stem_ == "-") or (_name_ in ("workers.slice", "workers-timing.slice")):
                continue
            if ("-" not in _stem_) or (_stem_.startswith("workers-") and (_stem_.count("-") == 1)):
                _found_.append(_name_)
        return _found_

    def _restrict(
        self,
        names: Annotated[list, "Slices of the user's systemd"],
        cpus: Annotated[str, "The cores they may use"],
    ):
        for _name_ in names:
            subprocess.run([self.config["systemctl"], "--user", "set-property", "--runtime", _name_, f"AllowedCPUs={cpus}"], check=True, capture_output=True)

    def _reserve(self):
        """Move everything else of the user off the timing cores; without that, no timing job starts"""
        _names_ = self._slices()
        # Written first: if this process ends before it gave the cores back, the file says that they are still reserved
        with open(self.config["reservation"], "w") as _file_:
            _file_.write("\n".join(_names_) + "\n")
        try:
            self._restrict(_names_, self.config["workCpus"])
        except subprocess.CalledProcessError as _error_:
            raise Refused(f"the timing cores could not be cleared, so the timing job did not start: {_error_.stderr.decode().strip()}")

    def _release(self):
        """Give the timing cores back; if that fails they stay reserved, which the status shows"""
        try:
            with open(self.config["reservation"]) as _file_:
                _names_ = _file_.read().split()
            self._restrict(_names_, self.config["allCpus"])
            os.unlink(self.config["reservation"])
        except (OSError, subprocess.CalledProcessError) as _error_:
            print(f"the timing cores stay reserved: {_error_}", file=sys.stderr, flush=True)

    def _status(self):
        _lines_ = []
        for _name_ in sorted(os.listdir(self.config["locks"])):
            _descriptor_ = os.open(os.path.join(self.config["locks"], _name_), os.O_RDONLY)
            try:
                fcntl.flock(_descriptor_, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _state_ = "free"
            except BlockingIOError:
                _state_ = "taken"
            os.close(_descriptor_)
            _lines_.append(f"{_name_:<12} {_state_}")
        if os.path.exists(self.config["reservation"]):
            _lines_.append("timing cores: reserved (everything but timing jobs is kept off them until a timing job ends)")
        else:
            _lines_.append("timing cores: shared")
        _lines_.append(f"this sandbox: {self.active} of {self.config['maxRequests']} requests waiting or running")
        return "\n".join(_lines_)


def main():
    _parser_ = argparse.ArgumentParser()
    for _name_ in ("config", "dir", "unit", "records", "records-limit", "scratch", "repo", "workers-root", "roles-root", "identity"):
        _parser_.add_argument(f"--{_name_}", required=True)
    _arguments_ = _parser_.parse_args()
    with open(_arguments_.config) as _file_:
        _config_ = json.load(_file_)
    # The file that says "reserved" is the user's, in memory, and gone after a restart
    _config_["reservation"] = os.path.join(os.environ["XDG_RUNTIME_DIR"], "workers", "timing-reserved")
    os.makedirs(os.path.dirname(_arguments_.records), exist_ok=True)
    Broker(_config_, _arguments_).serve()


if (__name__ == "__main__"):
    main()
