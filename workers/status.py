# The status of the workers, outside every sandbox (see docs/WORKERS.md):
#   workers status           a table
#   workers status --json    one document in the form that the dashboard reads (`workers watch`)
# Every value that the system does not measure says where it comes from: recorded (the broker's and the tools' records),
# derived (computed here), self-reported (asked inside the worker's own view) or claimed (the agent's own words). A claim is
# never shown as a fact: a worker that writes "passed" changes its claim and nothing else
# Files that an agent wrote (a form, a review, a line of status, a session file) are read as data: opened without following a
# link, within a size limit, with every failure caught, and every text is cut and made valid. Nothing read from them is run or
# used as a path. This program only reads, apart from its own notes on the last look (for processor shares, and for the answers
# that need git)
# This program is also the one place that fetches the workers' copies into the tools' own repository and counts commits there.
# The other uses, for the other actions of `workers`:
#   status.py --full-run <project> <manager> <commit>   for `workers take`: what the manager's records say about the whole suite on that commit
#   status.py --list                                    for `workers list` and `workers remove --merged`: of every worker, its unmerged
#                                                       commits, whether it is removable, and for an implementer that is not, why
#   status.py --unmerged <project>/<branch>/<name>      for `workers remove`: its commits that nobody else holds, asked now
#   status.py --forget <project>/<branch>/<name>        for `workers remove`: the tools' own repository lets the worker's copy go
#   status.py --reminder                                for the weekly reminder: one sentence if workers are removable, else nothing
import calendar
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from typing import Annotated

CUT = 4096
MANY = 20
WORKERS = 2000
ITEMS = 100
# How much of the end of a file of records or of a session is read
TAIL = 8 * 1024 * 1024
# The longest that a call waits for the tools' own repository of a project while another call uses it; that a fetch from a copy
# may take; and that tidying the repository may take (seconds)
HELD = 60
FETCH = 120
TIDY = 300
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
COMMIT = re.compile(r"[0-9a-f]{40,64}")


def cut(
    text: Annotated[object, "A text that an agent may have written"],
    limit: Annotated[int, "The most bytes of it that are passed on"] = CUT,
):
    """The text as valid UTF-8 of at most that many bytes; what is no character is replaced"""
    if not isinstance(text, str):
        text = str(text)
    return text.encode("utf-8", "replace")[:limit].decode("utf-8", "ignore")


def number(
    path: Annotated[str, "A file of the system's accounting that holds one number"],
):
    """That number, or nothing: when the file is not there, or says 'max'"""
    try:
        with open(path) as _file_:
            return int(_file_.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def field(
    path: Annotated[str, "A file of the system's accounting with lines of a name and a number"],
    name: Annotated[str, "The name that is looked for"],
):
    try:
        with open(path) as _file_:
            for _line_ in _file_:
                _words_ = _line_.split()
                if (len(_words_) == 2) and (_words_[0] == name):
                    return int(_words_[1])
    except (OSError, ValueError):
        pass
    return None


def known(
    **values: Annotated[object, "Values of which some may be unknown"],
):
    """Only the ones that are known: an unknown value is left out of the document, never written as null"""
    return {_key_: _value_ for _key_, _value_ in values.items() if _value_ is not None}


def below(
    root: Annotated[str, "A folder that no agent can exchange"],
    path: Annotated[str, "A path below it that an agent may have written"],
    limit: Annotated[int, "The most bytes that are read"],
    tail: Annotated[bool, "Read the end of the file instead of its start"] = False,
):
    """The bytes of a regular file, reached without a link at any level and opened once; nothing when it is not such a file"""
    _descriptor_ = None
    try:
        _descriptor_ = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        _parts_ = [_part_ for _part_ in path.split("/") if _part_]
        for _index_, _part_ in enumerate(_parts_):
            _last_ = (_index_ == len(_parts_) - 1)
            _flags_ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_NOCTTY if _last_ else os.O_DIRECTORY)
            _next_ = os.open(_part_, _flags_, dir_fd=_descriptor_)
            os.close(_descriptor_)
            _descriptor_ = _next_
        _status_ = os.fstat(_descriptor_)
        if not stat.S_ISREG(_status_.st_mode):
            return None
        if tail and (_status_.st_size > limit):
            os.lseek(_descriptor_, _status_.st_size - limit, os.SEEK_SET)
        _content_ = b""
        while (len(_content_) < limit):
            _more_ = os.read(_descriptor_, limit - len(_content_))
            if not _more_:
                break
            _content_ += _more_
        return _content_
    except OSError:
        return None
    finally:
        if _descriptor_ is not None:
            os.close(_descriptor_)


def firstLine(
    content: Annotated[bytes, "A file's start, or nothing"],
):
    """The first line that is not empty, as text; or nothing"""
    for _line_ in (content or b"").decode("utf-8", "replace").split("\n"):
        if _line_.strip():
            return cut(_line_.strip())
    return None


def lines(
    content: Annotated[bytes, "The end of a file of JSON lines"],
):
    """The lines that are whole JSON objects, oldest first; a line that is not is skipped"""
    _found_ = []
    for _line_ in (content or b"").split(b"\n"):
        if not _line_.startswith(b"{"):
            continue
        try:
            _entry_ = json.loads(_line_)
        except (ValueError, RecursionError):
            continue
        if isinstance(_entry_, dict):
            _found_.append(_entry_)
    return _found_


class Status:
    def __init__(
        self,
        config: Annotated[dict, "The programs and settings, from the system configuration"],
    ):
        self.config = config
        self.home = os.environ["HOME"]
        self.state = os.path.join(self.home, ".local/state/workers")
        self.plainState = os.path.join(self.home, ".local/state/workers-plain")
        self.folders = os.path.join(self.home, "workers")
        self.areas = os.path.join(self.home, "scratch/workers")
        self.runtime = os.path.join(os.environ["XDG_RUNTIME_DIR"], "workers")
        self.groups = f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/workers.slice"
        self.now = time.time()
        # The one program that reads and judges approvals
        _specification_ = importlib.util.spec_from_file_location("approve", config["approve"])
        self.approve = importlib.util.module_from_spec(_specification_)
        _specification_.loader.exec_module(self.approve)
        # The one parser for persistent worker starts
        _specification_ = importlib.util.spec_from_file_location("startSpec", config["startSpec"])
        self.startSpec = importlib.util.module_from_spec(_specification_)
        _specification_.loader.exec_module(self.startSpec)
        # This program's notes on its last look: processor times, and the answers that need git
        self.notes = os.path.join(self.runtime, "status-notes.json")
        try:
            with open(self.notes) as _file_:
                self.last = json.load(_file_)
        except (OSError, ValueError):
            self.last = {}
        if not isinstance(self.last, dict) or not all(isinstance(self.last.get(_key_, {}), dict) for _key_ in ("cpu", "commits")):
            self.last = {}
        self.next = {"time": self.now, "cpu": {}, "commits": {}}
        self.problems = []
        # What the counts of a project's workers rest on besides each copy, looked at once in a call
        self.projects = {}
        # For `workers list`, and for the table: of every worker its unmerged commits and whether it is removable; and for an
        # implementer whose work waits for a review, the command that starts its next reviewer
        self.rows = []
        self.commands = []
        # A displayed status may leave expensive commit counts to one detached refresh
        self.deferCounts = False
        self.pendingProjects = set()
        self.configPath = None
        # When the machine was started: stops for memory are counted from then
        try:
            with open("/proc/stat") as _file_:
                self.booted = [int(_line_.split()[1]) for _line_ in _file_ if _line_.startswith("btime ")][0]
        except (OSError, ValueError, IndexError):
            self.booted = 0
        # The jobs that the kernel stopped a process of, as their own records say: gathered while the workers are read
        self.jobStops = []

    def document(self):
        """The whole status, as the dashboard reads it"""
        _datasets_ = self._datasets()
        _stops_ = self._stops()
        _brokers_ = self._brokers()
        _workers_ = []
        for _project_ in sorted(self._listed(self.state)):
            for _branch_ in sorted(self._listed(os.path.join(self.state, _project_, "roles"))):
                for _name_ in sorted(self._listed(os.path.join(self.state, _project_, "roles", _branch_))):
                    if (len(_workers_) < WORKERS):
                        _workers_.append(self._worker(_project_, _branch_, _name_, _datasets_, _stops_, _brokers_))
        _workers_ += self._sessions(_brokers_, {(_worker_["project"], _worker_["branch"], _worker_["name"]) for _worker_ in _workers_})[: WORKERS - len(_workers_)]
        # The machine last: which jobs were stopped for memory is in the workers' records
        _document_ = {"version": 1, "generated": int(self.now), "machine": self._machine(_datasets_, _stops_, _brokers_), "workers": _workers_}
        self._remember()
        self._scheduleCounts()
        return _document_

    def fullRun(
        self,
        project: Annotated[str, "A project"],
        manager: Annotated[str, "One of its managers"],
        commit: Annotated[str, "A commit of that manager's copy"],
    ):
        """One sentence for `workers take`: whether the project's whole suite ran on that commit in the manager's copy, and how it ended"""
        _runs_ = [
            _run_
            for _run_ in self._runs(os.path.join(self.folders, project, "manager", manager))
            if (_run_.get("list") == "all") and (_run_.get("commit") == commit) and not _run_.get("stopped") and not _run_.get("time_limit")
        ]
        if not _runs_:
            return "no run of the project's whole suite is recorded for this commit of the manager's copy (the manager runs it with: queue acceptance --all)"
        _when_ = time.strftime("%Y-%m-%d %H:%M", time.localtime(self._time(_runs_[-1]) or 0))
        if (_runs_[-1]["exit"] == 0):
            return f"the project's whole suite passed on this commit of the manager's copy (recorded {_when_})"
        return f"the project's whole suite FAILED on this commit of the manager's copy (recorded {_when_}, exit status {_runs_[-1]['exit']})"

    def unmerged(
        self,
        project: Annotated[str, "The project"],
        branch: Annotated[str, "The worker's branch"],
        name: Annotated[str, "The worker"],
    ):
        """For `workers remove`: the commits of the worker's copy that nobody else holds, asked now: a number, - without a copy, ? when it cannot be said"""
        _copy_ = os.path.join(self.folders, project, branch, name, "repo")
        if not os.path.lexists(os.path.join(_copy_, ".git")):
            return "-"
        _answer_ = self._commits(project, branch, name, self._remote(f"file://{_copy_}", "HEAD", "refs/heads/*"), None, fresh=True)
        return str(_answer_["unmerged"]) if ("unmerged" in _answer_) else "?"

    def forget(
        self,
        project: Annotated[str, "The project"],
        branch: Annotated[str, "The worker's branch"],
        name: Annotated[str, "The worker"],
    ):
        """For `workers remove`: the tools' own repository lets go of what it holds of a removed worker's copy"""
        with self._held(project) as _mirror_:
            if not _mirror_:
                self.problems.append(f"the tools' own repository of {project} is in use by another call: it still holds the copy of {branch}/{name}, until that worker is asked about again or removed")
                return
            # (a manager's copy is there twice: as a worker's copy, and as a holder of other workers' commits)
            _places_ = [f"refs/copies/{branch}/{name}/"] + ([f"refs/managers/{name}/"] if (branch == "manager") else [])
            _held_ = self._git("--git-dir", _mirror_, "for-each-ref", "--format=%(refname)", *_places_)
            for _reference_ in (_held_.stdout.split() if _held_ and (_held_.returncode == 0) else []):
                self._git("--git-dir", _mirror_, "update-ref", "-d", _reference_)
            self._tidy(_mirror_, project)

    def reminder(self):
        """One sentence on the workers that can be removed and the space they hold; nothing when there are none"""
        _removable_ = [_worker_ for _worker_ in self.document()["workers"] if _worker_.get("removable", {}).get("value")]
        if not _removable_:
            return None
        _projects_ = sorted({_worker_["project"] for _worker_ in _removable_})
        _sizes_ = [_worker_[_key_]["used"] for _worker_ in _removable_ for _key_ in ("folder", "scratch") if isinstance(_worker_.get(_key_, {}).get("used"), int)]
        _holding_ = f" They hold {sum(_sizes_) / 2**30:.1f} GiB." if _sizes_ else ""
        _commands_ = "; ".join(f"workers remove --merged {_project_}" for _project_ in _projects_)
        return f"{len(_removable_)} worker(s) can be removed: their work is merged, nothing in their copies is uncommitted, and they do not run.{_holding_} To remove them (it can be undone for some days): {_commands_}"

    def _listed(
        self,
        folder: Annotated[str, "A folder of the tools' state"],
    ):
        try:
            return [_name_ for _name_ in os.listdir(folder) if NAME.fullmatch(_name_) and os.path.exists(os.path.join(folder, _name_))]
        except OSError:
            return []

    def _word(
        self,
        path: Annotated[str, "A small file of the tools' state"],
    ):
        try:
            with open(path) as _file_:
                return _file_.read(4096).strip()
        except OSError:
            return None

    def _git(
        self,
        *arguments: Annotated[str, "What git is asked, outside every repository that an agent writes"],
        timeout: Annotated[int, "The longest it may take, in seconds"] = 30,
    ):
        try:
            return subprocess.run([self.config["git"], *arguments], cwd="/", capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None

    def _remote(
        self,
        repository: Annotated[str, "A repository, asked as a remote: nothing in it runs"],
        *references: Annotated[str, "References, or patterns of references"],
    ):
        """What the repository's references point at: {reference: commit}"""
        _answer_ = self._git("ls-remote", repository, *references)
        _found_ = {}
        for _line_ in (_answer_.stdout if _answer_ and (_answer_.returncode == 0) else "").splitlines():
            _words_ = _line_.split()
            if (len(_words_) == 2) and COMMIT.fullmatch(_words_[0]):
                _found_[_words_[1]] = _words_[0]
        return _found_

    def _memory(
        self,
        group: Annotated[str, "A resource group"],
    ):
        return known(used=number(os.path.join(group, "memory.current")), limit=number(os.path.join(group, "memory.max")), peak=number(os.path.join(group, "memory.peak")))

    def _share(
        self,
        group: Annotated[str, "A resource group"],
        key: Annotated[str, "Its name in this program's notes"],
    ):
        """The processors the group has used since this program last looked, and the processor time it has used in all"""
        _used_ = field(os.path.join(group, "cpu.stat"), "usage_usec")
        if _used_ is None:
            return None, None
        self.next["cpu"][key] = _used_
        _before_ = self.last.get("cpu", {}).get(key)
        _elapsed_ = self.now - self.last.get("time", self.now)
        _share_ = round((_used_ - _before_) / 1e6 / _elapsed_, 2) if (_before_ is not None) and (_elapsed_ > 0.2) and (_used_ >= _before_) else None
        return _share_, _used_ // 1000000

    def _datasets(self):
        """Used bytes and limits of the workers' datasets, by mount point; nothing on a machine with plain folders"""
        if not self.config["helper"]:
            return {}
        try:
            _listed_ = subprocess.run([*self.config["helper"], "status"], capture_output=True, text=True, timeout=30)
            _roots_ = {}
            for _path_ in (self.folders, self.areas):
                _roots_[subprocess.run([self.config["findmnt"], "-rn", "-o", "SOURCE", "--mountpoint", _path_], capture_output=True, text=True, timeout=10).stdout.strip()] = _path_
        except (OSError, subprocess.SubprocessError):
            return {}
        _found_ = {}
        for _line_ in _listed_.stdout.splitlines():
            _words_ = _line_.split("\t")
            for _dataset_, _path_ in _roots_.items():
                if _dataset_ and (len(_words_) >= 3) and ((_words_[0] == _dataset_) or _words_[0].startswith(_dataset_ + "/")):
                    _found_[_path_ + _words_[0][len(_dataset_) :]] = known(used=int(_words_[1]) if _words_[1].isdigit() else None, limit=int(_words_[2]) if _words_[2].isdigit() and (_words_[2] != "0") else None)
        return _found_

    def _stops(self):
        """The processes stopped for memory since the machine was started, as the watcher wrote them down: newest first"""
        _found_ = [_entry_ for _entry_ in lines(below(self.state, "memory-stops.jsonl", TAIL, tail=True)) if isinstance(_entry_.get("time"), int) and (_entry_["time"] >= self.booted) and isinstance(_entry_.get("count"), int)]
        return _found_[::-1]

    def _brokers(self):
        """What every running sandbox's broker says of its requests: {unit: [request, ...]}"""
        _found_ = {}
        try:
            _units_ = os.listdir(self.runtime)
        except OSError:
            return _found_
        for _unit_ in _units_:
            # Only of a sandbox that runs: the folder of one that ended stays behind
            if not os.path.isdir(os.path.join(self.groups, "workers-agents.slice", f"{_unit_}.scope")):
                continue
            try:
                with open(os.path.join(self.runtime, _unit_, "state.json")) as _file_:
                    _requests_ = json.load(_file_).get("requests", [])
            except (OSError, ValueError, AttributeError):
                continue
            _found_[_unit_] = [_request_ for _request_ in _requests_ if isinstance(_request_, dict)]
        return _found_

    def _jobs(
        self,
        requests: Annotated[list, "A broker's requests"],
    ):
        _jobs_ = []
        for _request_ in requests[:MANY]:
            _job_ = known(mode=cut(_request_.get("mode", ""), 32), since=_request_.get("since") if isinstance(_request_.get("since"), int) else None)
            _job_["state"] = "running" if (_request_.get("state") == "running") else "waiting"
            _job_["command"] = cut(_request_.get("command") or "(the approved tests)")
            if (_job_["state"] == "running") and isinstance(_request_.get("unit"), str) and isinstance(_request_.get("slice"), str):
                _group_ = os.path.join(self.groups, os.path.basename(_request_["slice"]), os.path.basename(_request_["unit"]))
                _memory_ = known(used=number(os.path.join(_group_, "memory.current")), peak=number(os.path.join(_group_, "memory.peak")))
                if _memory_:
                    _job_["memory"] = _memory_
                _share_, _ = self._share(_group_, os.path.basename(_request_["unit"]))
                if _share_ is not None:
                    _job_["cpu"] = {"share": _share_}
            _jobs_.append(_job_)
        return _jobs_

    def _machine(
        self,
        datasets: Annotated[dict, "The datasets' sizes"],
        stops: Annotated[list, "The stops for memory"],
        brokers: Annotated[dict, "The brokers' requests"],
    ):
        _machine_ = {"memory": self._memory(self.groups), "agentsMemory": self._memory(os.path.join(self.groups, "workers-agents.slice"))}
        # The agents' shared limit of processor time, as the system holds it: "<microseconds> <per microseconds>", or "max"
        _share_, _ = self._share(os.path.join(self.groups, "workers-agents.slice"), "workers-agents.slice")
        try:
            with open(os.path.join(self.groups, "workers-agents.slice", "cpu.max")) as _file_:
                _quota_, _period_ = _file_.read().split()
            _limit_ = round(int(_quota_) / int(_period_), 2)
        except (OSError, ValueError):
            _limit_ = None
        _machine_["agentsCpu"] = known(share=_share_, limit=_limit_)
        # How many: the watcher's count, which misses none. Which ones: an agent's, if the watcher still found its resource group
        # (a job's group ends with the job); a job's, from the job's own record, which is written while its group still exists
        _last_ = list(self.jobStops)
        for _stop_ in stops:
            _who_ = self._unit(_stop_.get("unit"))
            if _who_ and (_who_[1] == "agent"):
                _last_.append({"time": _stop_["time"], "worker": _who_[0], "what": "agent"})
        _last_ = sorted(_last_, key=lambda _stop_: _stop_["time"], reverse=True)[:MANY]
        _machine_["memoryStops"] = {"count": sum(_stop_["count"] for _stop_ in stops), "last": [{_key_: _stop_[_key_] for _key_ in ("time", "worker", "what")} for _stop_ in _last_]}
        _machine_["cpus"] = known(count=os.cpu_count(), timing=self.config["timingCpus"] or None, timingReserved=os.path.exists(os.path.join(self.runtime, "timing-reserved")))
        # The slots are lock files: one that cannot be locked now is taken
        _taken_ = {"slot": [0, 0], "parallel": [0, 0], "timing": [0, 0]}
        try:
            _locks_ = sorted(os.listdir(self.config["locks"]))
        except OSError:
            _locks_ = []
        for _lock_ in _locks_:
            _kind_ = _lock_.rstrip("0123456789")
            if (_kind_ in _taken_):
                _taken_[_kind_][1] += 1
                _taken_[_kind_][0] += 0 if self._free(os.path.join(self.config["locks"], _lock_)) else 1
        _requests_ = [_request_ for _list_ in brokers.values() for _request_ in _list_]
        _machine_["queue"] = {
            "slots": {"taken": _taken_["slot"][0], "total": _taken_["slot"][1]},
            "parallel": {"taken": _taken_["parallel"][0], "total": _taken_["parallel"][1]},
            "timing": {"taken": _taken_["timing"][0], "total": _taken_["timing"][1]},
            "exclusive": any((_request_.get("mode") == "exclusive") and (_request_.get("state") == "running") for _request_ in _requests_),
            "waiting": sum(1 for _request_ in _requests_ if (_request_.get("state") != "running")),
        }
        _disk_ = known(workers=datasets.get(self.folders), scratch=datasets.get(self.areas))
        if _disk_:
            _machine_["disk"] = _disk_
        return _machine_

    def _free(
        self,
        path: Annotated[str, "A lock file of the queue"],
    ):
        try:
            _descriptor_ = os.open(path, os.O_RDONLY)
        except OSError:
            return True
        try:
            fcntl.flock(_descriptor_, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
        finally:
            os.close(_descriptor_)

    def _unit(
        self,
        unit: Annotated[object, "The name of a resource group, or nothing"],
    ):
        """Whose it is: the worker as <project>/<branch>/<name>, and whether it is the agent or a job; nothing when it does not say"""
        _match_ = re.fullmatch(r"(job-)?worker:([^:]+):([^:]+):([^:]+?)(-\d+)?\.scope", unit) if isinstance(unit, str) else None
        if not _match_ or (bool(_match_.group(1)) != bool(_match_.group(5))):
            return None
        return "/".join(_match_.group(2, 3, 4)), ("job" if _match_.group(1) else "agent")

    def _time(
        self,
        run: Annotated[dict, "A record of a run"],
    ):
        """When the run started, in seconds since 1970; or nothing"""
        try:
            return int(time.mktime(time.strptime(run["id"][:15], "%Y%m%dT%H%M%S")))
        except (KeyError, TypeError, ValueError):
            return None

    def _runs(
        self,
        folder: Annotated[str, "A worker's folder"],
        records: Annotated[str, "Its records, below that folder"] = "records/runs.jsonl",
    ):
        """The finished runs that the broker recorded, oldest first: of every run the line of its end"""
        _ended_ = {}
        for _entry_ in lines(below(folder, records, TAIL, tail=True)):
            if isinstance(_entry_.get("id"), str) and isinstance(_entry_.get("exit"), int):
                _ended_[_entry_["id"]] = _entry_
        return list(_ended_.values())

    def _steps(
        self,
        folder: Annotated[str, "A worker's folder"],
        name: Annotated[str, "The worker, for a message"],
        sessions: Annotated[str, "The session folder, when it is not below the worker's folder"] = None,
    ):
        """The agent's own to-do list, from the last entry that the to-do tool wrote into the newest session file"""
        # The newest session file, at most two folders deep, never through a link
        _newest_ = (0, None)
        _sessions_ = sessions or os.path.join(folder, "sessions")
        try:
            for _entry_ in os.scandir(_sessions_):
                _inside_ = [_entry_]
                if _entry_.is_dir(follow_symlinks=False):
                    _inside_ = list(os.scandir(_entry_.path))
                for _file_ in _inside_:
                    if _file_.name.endswith(".jsonl") and _file_.is_file(follow_symlinks=False):
                        _newest_ = max(_newest_, (_file_.stat(follow_symlinks=False).st_mtime, os.path.relpath(_file_.path, _sessions_)))
        except OSError:
            return None
        if _newest_[1] is None:
            return None
        _lists_ = [_entry_ for _entry_ in lines(below(_sessions_, _newest_[1], TAIL, tail=True)) if (_entry_.get("type") == "custom") and (_entry_.get("customType") == "rpiv-todo-state")]
        if not _lists_:
            return None
        # The form that the pinned to-do tool writes: data.tasks, each with a subject and one of four states
        _states_ = {"completed": "done", "in_progress": "in work", "pending": "open"}
        _tasks_ = _lists_[-1].get("data", {}).get("tasks") if isinstance(_lists_[-1].get("data"), dict) else None
        if not isinstance(_tasks_, list) or not all(isinstance(_task_, dict) and isinstance(_task_.get("subject"), str) and (_task_.get("status") in (*_states_, "deleted")) for _task_ in _tasks_):
            self.problems.append(f"the to-do list of {name} is not in the form that this tool knows of the to-do extension: it is left out")
            return None
        _tasks_ = [_task_ for _task_ in _tasks_ if (_task_["status"] != "deleted")]
        _current_ = [_task_ for _task_ in _tasks_ if (_task_["status"] == "in_progress")]
        _steps_ = {"done": sum(1 for _task_ in _tasks_ if (_task_["status"] == "completed")), "total": len(_tasks_), "source": "claimed"}
        if _current_:
            _steps_["current"] = cut(_current_[0].get("activeForm") if isinstance(_current_[0].get("activeForm"), str) else _current_[0]["subject"])
        # When the list last changed: the time the entry carries (universal time), if it carries one that can be read
        try:
            _steps_["changed"] = calendar.timegm(time.strptime(str(_lists_[-1].get("timestamp"))[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            pass
        _steps_["items"] = [{"text": cut(_task_["subject"]), "state": _states_[_task_["status"]]} for _task_ in _tasks_[:ITEMS]]
        return _steps_

    @contextlib.contextmanager
    def _held(
        self,
        project: Annotated[str, "The project"],
    ):
        """The tools' own repository of a project, for this call alone; nothing if another call keeps it longer than this one waits"""
        # Every copy is fetched into it, and what no reference needs any more is removed from it: two calls at once would take
        # away each other's objects, so one works at a time
        _mirror_ = os.path.join(self.state, project, "mirror.git")
        _descriptor_ = os.open(os.path.join(self.state, project, "mirror.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _deadline_ = time.monotonic() + HELD
            while True:
                try:
                    fcntl.flock(_descriptor_, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if (time.monotonic() > _deadline_):
                        _mirror_ = None
                        break
                    time.sleep(0.05)
            if _mirror_ and not os.path.isdir(_mirror_):
                self._git("init", "--quiet", "--bare", _mirror_)
            yield _mirror_
        finally:
            os.close(_descriptor_)

    def _fetch(
        self,
        mirror: Annotated[str, "The tools' own repository"],
        repository: Annotated[str, "A repository that is only a remote here: nothing in it runs"],
        target: Annotated[str, "Where its branches go: refs/<target>/"],
    ):
        """Whether the fetch worked, and whether the tools' repository may now hold objects that no reference needs"""
        _answer_ = self._git("--git-dir", mirror, "fetch", "--no-tags", "--prune", "--porcelain", f"file://{repository}", f"+refs/heads/*:refs/{target}/*", timeout=FETCH)
        _worked_ = bool(_answer_) and (_answer_.returncode == 0)
        # After a fetch that broke off; after a branch was moved back or aside (+), or is gone (-)
        return _worked_, not _worked_ or any(_line_[:1] in ("+", "-") for _line_ in _answer_.stdout.splitlines())

    def _tidy(
        self,
        mirror: Annotated[str, "The tools' own repository"],
        project: Annotated[str, "The project, for a message"],
    ):
        """Remove what no reference needs: the tools keep nothing of a worker that the worker's own branches have dropped"""
        _tidied_ = self._git("--git-dir", mirror, "gc", "--quiet", "--prune=now", timeout=TIDY)
        if not _tidied_ or (_tidied_.returncode != 0):
            self.problems.append(f"the tools' own repository of {project} could not be tidied: it may hold more than the workers' copies do, until the next call")

    def _basis(
        self,
        project: Annotated[str, "The project"],
    ):
        """The project itself and its managers' copies, and a key that changes when a branch of any of them moves"""
        if project not in self.projects:
            _main_ = self._word(os.path.join(self.state, project, "main"))
            _managers_ = {}
            for _manager_ in sorted(self._listed(os.path.join(self.folders, project, "manager"))):
                _path_ = os.path.join(self.folders, project, "manager", _manager_, "repo")
                if os.path.isdir(_path_):
                    _managers_[_manager_] = _path_
            _heads_ = [self._remote(_main_, "refs/heads/*") if _main_ else {}] + [self._remote(f"file://{_path_}", "refs/heads/*") for _path_ in _managers_.values()]
            _key_ = hashlib.sha256(json.dumps([_heads_, sorted(_managers_)], sort_keys=True).encode()).hexdigest()
            self.projects[project] = {
                "main": _main_,
                "managers": _managers_,
                "key": _key_,
                "referenceCount": sum(len(_head_) for _head_ in _heads_),
                "fetched": None,
            }
            self.next["commits"][project] = {"key": _key_, "workers": {}}
        return self.projects[project]

    def _commits(
        self,
        project: Annotated[str, "The project"],
        branch: Annotated[str, "The worker's branch"],
        name: Annotated[str, "The worker"],
        heads: Annotated[dict, "The branches of its copy and their commits, as the copy says now"],
        current: Annotated[str, "The commit that stands for its work, or nothing"],
        fresh: Annotated[bool, "Ask again, whatever was noted at the last look"] = False,
    ):
        """How the copy stands against its branch in the project (ahead, behind), and how many of its commits nobody else holds
        (unmerged); empty when that cannot be said now"""
        # The one place that fetches into the tools' own repository and counts there. An answer stands until a branch moves:
        # of the copy, of the project, or of a manager's copy. An answer that could not be made is not kept
        _basis_ = self._basis(project)
        _key_ = hashlib.sha256(json.dumps([heads, current], sort_keys=True).encode()).hexdigest()
        _noted_ = self.last.get("commits", {}).get(project, {})
        _answer_ = _noted_.get("workers", {}).get(f"{branch}/{name}") if (_noted_.get("key") == _basis_["key"]) and not fresh else None
        if not isinstance(_answer_, dict) or (_answer_.get("heads") != _key_):
            if self.deferCounts and not fresh and (_basis_["referenceCount"] >= 50):
                self.pendingProjects.add(project)
                return {"pending": True}
            _answer_ = self._counted(project, branch, name, current, _basis_)
            if _answer_ is not None:
                _answer_["heads"] = _key_
        if _answer_ is None:
            return {}
        self.next["commits"][project]["workers"][f"{branch}/{name}"] = _answer_
        return _answer_

    def _taken(
        self,
        mirror: Annotated[str, "The tools' own repository"],
        branch: Annotated[str, "The worker's branch"],
        name: Annotated[str, "The worker"],
    ):
        """References of a manager's copy whose tip tree the project holds in one of its commits"""
        if (branch != "manager"):
            return []
        _projectTrees_ = self._git("--git-dir", mirror, "log", "--format=%T", "--glob=refs/project/*")
        _references_ = self._git("--git-dir", mirror, "for-each-ref", "--format=%(refname)", f"refs/copies/{branch}/{name}/")
        if not _projectTrees_ or (_projectTrees_.returncode != 0) or not _references_ or (_references_.returncode != 0):
            return []
        _heldTrees_ = set(_projectTrees_.stdout.split())
        _taken_ = []
        for _reference_ in _references_.stdout.split():
            _tree_ = self._git("--git-dir", mirror, "rev-parse", f"{_reference_}^{{tree}}")
            if _tree_ and (_tree_.returncode == 0) and (_tree_.stdout.strip() in _heldTrees_):
                _taken_.append(_reference_)
        return _taken_

    def _counted(
        self,
        project: Annotated[str, "The project"],
        branch: Annotated[str, "The worker's branch"],
        name: Annotated[str, "The worker"],
        current: Annotated[str, "The commit that stands for its work, or nothing"],
        basis: Annotated[dict, "The project and its managers' copies"],
    ):
        """Fetch and count; nothing when a step of it failed"""
        if not basis["main"]:
            return None
        with self._held(project) as _mirror_:
            if not _mirror_:
                self.problems.append(f"the tools' own repository of {project} is in use by another call: the commits of {branch}/{name} are not counted this time")
                return None
            # The project and the managers' copies once in a call, the worker's copy each time it is asked about
            _loose_ = False
            if basis["fetched"] is None:
                _steps_ = [self._fetch(_mirror_, basis["main"], "project")]
                _steps_ += [self._fetch(_mirror_, _path_, f"managers/{_manager_}") for _manager_, _path_ in basis["managers"].items()]
                basis["fetched"] = all(_step_[0] for _step_ in _steps_)
                _loose_ = any(_step_[1] for _step_ in _steps_)
            _worked_, _dropped_ = self._fetch(_mirror_, os.path.join(self.folders, project, branch, name, "repo"), f"copies/{branch}/{name}")
            if _loose_ or _dropped_:
                self._tidy(_mirror_, project)
            if not (basis["fetched"] and _worked_):
                return None
            # Who else holds a commit: the project, and every manager's copy but the worker's own
            _others_ = ["--glob=refs/project/*"] + [f"--glob=refs/managers/{_manager_}/*" for _manager_ in basis["managers"] if (branch, name) != ("manager", _manager_)]
            # `workers take` squashes. A project commit with the same tree as a manager branch tip holds that branch's work,
            # although none of the manager's commit names reached the project
            _others_ += self._taken(_mirror_, branch, name)
            _counts_ = {"unmerged": ["rev-list", "--count", f"--glob=refs/copies/{branch}/{name}/*", "--not", *_others_]}
            if current:
                _counts_["ahead"] = ["rev-list", "--count", current, "--not", f"refs/project/{branch}"]
                _counts_["behind"] = ["rev-list", "--count", f"refs/project/{branch}", "--not", current]
            _answer_ = {}
            for _what_, _arguments_ in _counts_.items():
                _counted_ = self._git("--git-dir", _mirror_, *_arguments_)
                if not _counted_ or (_counted_.returncode != 0) or not _counted_.stdout.strip().isdigit():
                    # (a manager has no branch of its name in the project: only its unmerged commits are counted)
                    if (_what_ == "unmerged"):
                        return None
                    continue
                _answer_[_what_] = int(_counted_.stdout)
            return _answer_

    def _worker(
        self,
        project: Annotated[str, "The project"],
        branch: Annotated[str, "The branch"],
        name: Annotated[str, "The worker's name"],
        datasets: Annotated[dict, "The datasets' sizes"],
        stops: Annotated[list, "The stops for memory"],
        brokers: Annotated[dict, "The brokers' requests"],
    ):
        _full_ = f"{project}/{branch}/{name}"
        _folder_ = os.path.join(self.folders, project, branch, name)
        _unit_ = f"worker:{project}:{branch}:{name}"
        _group_ = os.path.join(self.groups, "workers-agents.slice", f"{_unit_}.scope")
        _role_ = self._word(os.path.join(self.state, project, "roles", branch, name))
        _role_ = _role_ if (_role_ in ("implementer", "reviewer", "deep-reviewer", "manager")) else "implementer"
        _worker_ = {"project": project, "branch": branch, "name": name, "role": _role_}
        try:
            self.startSpec.load(self.state, _full_)
            _worker_["command"] = {"value": self.startSpec.shortCommand(_full_), "source": "recorded"}
        except self.startSpec.Refused as _refusal_:
            if os.path.lexists(self.startSpec.recordPath(self.state, _full_)):
                self.problems.append(str(_refusal_))
        _places_ = {
            "copy": os.path.join(_folder_, "repo"),
            "reports": os.path.join(_folder_, "reports"),
            "records": os.path.join(_folder_, "records"),
            "scratch": os.path.join(self.areas, project, branch, name),
        }
        if (_role_ != "manager"):
            _places_["task"] = os.path.join(self.folders, project, "instructions", branch, f"{name}.md")
        _worker_["places"] = _places_

        ## Step 1. Measured: whether it runs, what it uses, how full its folder and its scratch area are
        _running_ = os.path.isdir(_group_)
        _started_ = self._word(os.path.join(self.state, project, "starts", branch, name))
        _started_ = int(_started_) if _started_ and _started_.isdigit() else None
        _worker_["running"] = known(value=_running_, since=_started_ if _running_ else None)
        if _started_:
            _worker_["lastRun"] = _started_
        if _running_:
            _worker_["memory"] = self._memory(_group_)
            _share_, _seconds_ = self._share(_group_, _unit_)
            _worker_["cpu"] = known(share=_share_, seconds=_seconds_)
            _worker_["jobs"] = self._jobs(brokers.get(_unit_, []))
        for _key_, _path_ in (("folder", _folder_), ("scratch", os.path.join(self.areas, project, branch, name))):
            if datasets.get(_path_):
                _worker_[_key_] = datasets[_path_]

        ## Step 2. Recorded: its runs, and the commit its copy is at, asked from outside
        _runs_ = self._runs(_folder_)
        # Stopped for memory since the machine was started: its agent, as far as the watcher knew whose it was, and its jobs
        _count_ = sum(_stop_["count"] for _stop_ in stops if self._unit(_stop_.get("unit")) == (_full_, "agent"))
        for _run_ in _runs_:
            _ended_ = (self._time(_run_) or 0) + (_run_.get("duration_s") if isinstance(_run_.get("duration_s"), int) else 0)
            if isinstance(_run_.get("memory_stops"), int) and (_run_["memory_stops"] > 0) and (_ended_ >= self.booted):
                self.jobStops.append({"time": _ended_, "worker": _full_, "what": "job"})
                _count_ += _run_["memory_stops"]
        if _count_:
            _worker_["memoryStops"] = {"count": _count_}
        _copy_ = os.path.join(_folder_, "repo")
        # Which commit is the current one is decided where the approvals are: an implementer's own branch, not what is checked out
        _judged_ = self.approve.Worker(self.config["approveConfig"], _full_)
        _heads_ = self._remote(f"file://{_copy_}", "HEAD", "refs/heads/*") if os.path.isdir(_copy_) else {}
        _current_ = _heads_.get(_judged_.reference())

        def shown(run, command=False):
            _shown_ = known(mode=cut(run.get("mode", ""), 32), time=self._time(run), exit=run["exit"], duration=run.get("duration_s") if isinstance(run.get("duration_s"), int) else None)
            if _current_ and isinstance(run.get("commit"), str):
                _shown_["onCurrentCommit"] = (run["commit"] == _current_)
            if command:
                _shown_["command"] = cut(" ".join(_word_ for _word_ in run.get("command", []) if isinstance(_word_, str)) if (run.get("kind") != "acceptance") else "(the approved tests)")
            return _shown_

        if _runs_:
            _worker_["lastQueuedRun"] = {**shown(_runs_[-1]), "source": "recorded"}
            _worker_["runs"] = [shown(_run_, command=True) for _run_ in _runs_[::-1][:MANY]]

        # How its copy stands against the project and the managers' copies: counted for every role, since every role's worker can
        # be removed, and shown for an implementer
        _counted_ = self._commits(project, branch, name, _heads_, _current_ if (_role_ == "implementer") else None) if _heads_ else {}
        _removable_, _removeWithMerged_, _why_ = False, False, "-"

        ## Step 3. An implementer: its approval, the approved tests, its commits, its reviews
        if (_role_ == "implementer"):
            try:
                _approval_ = _judged_.approval()
                _lock_ = self.approve.state(_judged_)
            except self.approve.Refused as _refusal_:
                self.problems.append(str(_refusal_))
                _approval_, _lock_ = None, "no approval"
            _intent_ = {"approved": _approval_ is not None, "source": "recorded"}
            if _approval_:
                _intent_.update(known(approach=_approval_.get("approach"), approvedAt=_approval_.get("time")))
                if not _approval_.get("withoutForm"):
                    # The form as it is now against the one that was approved; a form that cannot be read has changed
                    _form_ = below(_folder_, "reports/intent.md", self.config["approveConfig"]["maxFormBytes"] + 1)
                    _intent_["changedSinceApproval"] = (_form_ is None) or (hashlib.sha256(_form_).hexdigest() != _approval_.get("fingerprint"))
            _worker_["intent"] = _intent_
            # The approved tests: the last whole run of exactly that list, from the broker's records
            _tested_ = [_run_ for _run_ in _runs_ if (_run_.get("kind") == "acceptance") and not _run_.get("stopped") and not _run_.get("time_limit")]
            if _approval_ and _approval_.get("listDigest"):
                _tested_ = [_run_ for _run_ in _tested_ if (_run_.get("listDigest") == _approval_["listDigest"])]
            if not _tested_:
                _worker_["acceptance"] = {"value": "never run", "source": "recorded"}
            else:
                _onCurrent_ = bool(_current_) and (_tested_[-1].get("commit") == _current_)
                _value_ = "failed" if (_tested_[-1]["exit"] != 0) else ("passed" if _onCurrent_ else "stale")
                _worker_["acceptance"] = known(value=_value_, onCurrentCommit=_onCurrent_, time=self._time(_tested_[-1]), source="recorded")
            _commits_ = known(ahead=_counted_.get("ahead"), behind=_counted_.get("behind"), pending=_counted_.get("pending"), source="derived")
            _said_ = [_run_.get("uncommitted_as_reported") for _run_ in _runs_ if (_run_.get("uncommitted_as_reported") in ("yes", "no"))]
            if _said_:
                _commits_["uncommitted"] = {"value": (_said_[-1] == "yes"), "source": "self-reported"}
            _worker_["commits"] = _commits_
            # The reviewers that were started against it, and the commit each started from, as the launcher wrote them down
            _reviews_ = {"count": 0, "outdated": 0, "verdicts": [], "source": "derived"}
            # Reviewed: a reviewer that started from the current commit has written its review. That the file is there is a
            # fact; what it says is the reviewer's word
            _reviewed_ = False
            for _reviewer_ in sorted(self._listed(os.path.join(self.state, project, "reviews", branch, name))):
                _noted_ = (self._word(os.path.join(self.state, project, "reviews", branch, name, _reviewer_)) or "").split()
                _fromCurrent_ = bool(_noted_) and bool(_current_) and (_noted_[0] == _current_)
                _review_ = below(os.path.join(self.folders, project, branch, _reviewer_), "reports/review.md", 2 * CUT)
                _reviews_["count"] += 1
                _reviews_["outdated"] += 0 if _fromCurrent_ else 1
                _reviewed_ = _reviewed_ or (_fromCurrent_ and (_review_ is not None))
                _verdict_ = firstLine(_review_)
                if _verdict_ and (len(_reviews_["verdicts"]) < MANY):
                    _reviews_["verdicts"].append({"by": _reviewer_, "value": _verdict_, "source": "claimed"})
            _worker_["reviews"] = _reviews_
            # Merged: it has commits of its own, and the project or a manager's copy holds every one of them. Removable: merged,
            # its last word is that nothing is uncommitted, and it does not run
            _ahead_ = _counted_.get("ahead") or 0
            _merged_ = (_ahead_ > 0) and (_counted_.get("unmerged") == 0)
            _removable_ = _merged_ and bool(_said_) and (_said_[-1] == "no") and not _running_
            _worker_["removable"] = {"value": _removable_, "source": "derived"}
            _removeWithMerged_ = _removable_
            # In words, for `workers remove --merged`, which names the implementers it leaves
            if "unmerged" not in _counted_:
                _why_ = "its commits could not be counted"
            elif (_counted_["unmerged"] > 0):
                _why_ = f"{_counted_['unmerged']} commit(s) that neither the project nor a manager's copy holds"
            elif (_ahead_ == 0):
                _why_ = "it has no commits of its own"
            elif not _said_:
                _why_ = "it has not reported whether anything is uncommitted (it has no queued run)"
            elif (_said_[-1] != "no"):
                _why_ = "its last queued run reported uncommitted changes"
            elif _running_:
                _why_ = "it runs"

        # A reviewer follows the implementers it was started against. The removal itself asks again whether its copy is clean,
        # and refuses a reviewer that runs
        elif (_role_ == "reviewer"):
            _reviewsRoot_ = os.path.join(self.state, project, "reviews", branch)
            _reviewed_ = [
                _implementer_
                for _implementer_ in self._listed(_reviewsRoot_)
                if os.path.isfile(os.path.join(_reviewsRoot_, _implementer_, name))
            ]
            _present_ = [
                _implementer_
                for _implementer_ in _reviewed_
                if self._word(os.path.join(self.state, project, "roles", branch, _implementer_)) == "implementer"
            ]
            if _present_:
                _why_ = f"reviewed implementer(s) still present: {', '.join(_present_)}"
            elif _reviewed_:
                _removeWithMerged_ = True
            else:
                _why_ = "it has no recorded implementer"
            _worker_["review"] = {
                "implementers": _reviewed_[:MANY],
                "removableWithMerged": _removeWithMerged_,
                "source": "derived",
            }
        elif (_role_ in ("manager", "deep-reviewer")):
            _worker_["removal"] = {"value": "removed by its own command", "source": "derived"}

        ## Step 4. Claimed: the agent's to-do list, and its own line on how it stands
        _steps_ = self._steps(_folder_, _full_)
        if _steps_:
            _worker_["steps"] = _steps_
        _claim_ = firstLine(below(_folder_, "reports/status.md", 2 * CUT))
        if _claim_:
            _worker_["claim"] = {"value": _claim_, "source": "claimed"}

        ## Step 5. Where it stands, from the above; only "ready for review" rests on the agent's word, and says so
        _state_, _source_ = "idle", "derived"
        if (_role_ == "implementer"):
            _worked_ = bool(_current_) and bool(_approval_) and (_approval_.get("copyCommit") not in (None, _current_))
            _state_ = "planned"
            if _approval_:
                _state_ = "implementing" if (_lock_ == "open") and (_worked_ or (_ahead_ > 0)) else "approved"
            if (_state_ == "implementing") and (_claim_ or "").lower().startswith("ready for review"):
                _state_, _source_ = "ready for review", "claimed"
            if _approval_ and _reviewed_:
                _state_, _source_ = "reviewed", "derived"
            if _merged_:
                _state_, _source_ = ("removable" if _removable_ else "merged"), "derived"
            # The next user action is composed here, never taken from the agent's text
            if (_state_ == "planned"):
                _worker_["nextStep"] = {"command": f"workers approve {_full_}", "source": "derived"}
            elif (_state_ in ("implementing", "ready for review")):
                _taken_ = set(self._listed(os.path.join(self.state, project, "roles", branch)) + self._listed(os.path.join(self.state, project, "roles-removed", branch)))
                _free_ = [f"{name[:40]}-r{_number_}" for _number_ in range(1, len(_taken_) + 2) if f"{name[:40]}-r{_number_}" not in _taken_][0]
                _main_ = self._word(os.path.join(self.state, project, "main")) or f"~/{project}"
                _command_ = f"cd {_main_} && pi --role reviewer --branch {branch} --name {_free_} --of {name}"
                _worker_["nextStep"] = {"command": _command_, "source": "derived"}
                self.commands.append((_full_, _command_, f"{self.folders}/{project}/instructions/{branch}/{_free_}.md"))
            elif (_state_ == "removable"):
                _worker_["nextStep"] = {"command": f"workers remove --merged {project}", "source": "derived"}
        _worker_["state"] = {"value": _state_, "source": _source_}
        # For `workers list`: - without a copy, ? when the commits could not be counted
        _held_ = "-" if not os.path.lexists(os.path.join(_copy_, ".git")) else str(_counted_.get("unmerged", "?"))
        self.rows.append((project, branch, name, _held_, "yes" if _removeWithMerged_ else "no", _why_))
        return _worker_

    def _sessions(
        self,
        brokers: Annotated[dict, "The brokers' requests"],
        taken: Annotated[set, "The workers that are listed already"],
    ):
        """The ordinary pi sessions that run now: each has a sandbox, a broker and jobs like a worker, and no folder"""
        _found_ = []
        try:
            _scopes_ = sorted(os.listdir(os.path.join(self.groups, "workers-agents.slice")))
        except OSError:
            return _found_
        for _scope_ in _scopes_:
            _match_ = re.fullmatch(r"pi-(.+)-(\d+)\.scope", _scope_)
            if not _match_ or not NAME.fullmatch(_match_.group(1)) or ((_match_.group(1), "plain", _match_.group(2)) in taken):
                continue
            _group_ = os.path.join(self.groups, "workers-agents.slice", _scope_)
            _share_, _seconds_ = self._share(_group_, _scope_[: -len(".scope")])
            _key_ = _match_.group(1)
            _session_ = {"project": _key_, "branch": "plain", "name": _match_.group(2), "role": "plain", "state": {"value": "idle", "source": "derived"}}
            _session_.update({"running": {"value": True}, "memory": self._memory(_group_), "cpu": known(share=_share_, seconds=_seconds_), "jobs": self._jobs(brokers.get(_scope_[: -len(".scope")], []))})
            _records_ = os.path.join(self.plainState, _key_, "records.jsonl")
            _session_["places"] = {"records": _records_, "scratch": os.path.join(self.areas, _key_, "plain", "session")}
            _found_.append(_session_)
        return _found_

    def _scheduleCounts(self):
        """Start one detached refresh for commit counts that this displayed status deliberately left unknown"""
        if not self.pendingProjects or not self.configPath:
            return
        try:
            subprocess.Popen(
                [sys.executable, "-I", os.path.abspath(__file__), "--config", self.configPath, "--refresh-commits", *sorted(self.pendingProjects)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError:
            pass

    def refreshCommits(
        self,
        projects: Annotated[list, "Projects whose displayed commit counts are being prepared"],
    ):
        """Count every worker of the named projects, one detached refresh at a time"""
        try:
            os.makedirs(self.runtime, mode=0o700, exist_ok=True)
            _descriptor_ = os.open(os.path.join(self.runtime, "status-refresh.lock"), os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(_descriptor_, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        try:
            for _project_ in projects:
                if not NAME.fullmatch(_project_):
                    continue
                for _branch_ in sorted(self._listed(os.path.join(self.state, _project_, "roles"))):
                    for _name_ in sorted(self._listed(os.path.join(self.state, _project_, "roles", _branch_))):
                        _copy_ = os.path.join(self.folders, _project_, _branch_, _name_, "repo")
                        if not os.path.isdir(_copy_):
                            continue
                        _heads_ = self._remote(f"file://{_copy_}", "HEAD", "refs/heads/*")
                        if not _heads_:
                            continue
                        _judged_ = self.approve.Worker(self.config["approveConfig"], f"{_project_}/{_branch_}/{_name_}")
                        _role_ = self._word(os.path.join(self.state, _project_, "roles", _branch_, _name_))
                        _current_ = _heads_.get(_judged_.reference()) if (_role_ == "implementer") else None
                        self._commits(_project_, _branch_, _name_, _heads_, _current_, fresh=True)
            self._remember(commitsOnly=True)
        finally:
            os.close(_descriptor_)

    def _remember(
        self,
        commitsOnly: Annotated[bool, "Merge only refreshed commit counts into the latest display notes"] = False,
    ):
        """This program's notes for its next look, as a new file put in place by a rename"""
        try:
            os.makedirs(self.runtime, mode=0o700, exist_ok=True)
            _remembered_ = self.next
            if commitsOnly:
                try:
                    with open(self.notes) as _file_:
                        _remembered_ = json.load(_file_)
                except (OSError, ValueError):
                    _remembered_ = {"time": self.now, "cpu": {}, "commits": {}}
                if not isinstance(_remembered_, dict) or not isinstance(_remembered_.get("commits"), dict):
                    _remembered_ = {"time": self.now, "cpu": {}, "commits": {}}
                _remembered_["commits"].update(self.next["commits"])
            with open(f"{self.notes}.{os.getpid()}", "w") as _file_:
                json.dump(_remembered_, _file_)
            os.replace(f"{self.notes}.{os.getpid()}", self.notes)
        except OSError:
            pass


def table(
    document: Annotated[dict, "The status document"],
    commands: Annotated[list, "For each implementer whose work waits for a review: the worker, the command that starts its next reviewer, and that reviewer's task file"],
):
    """The same values for a terminal; an agent's words stand apart, in the last column, and are cut short"""
    _machine_ = document["machine"]
    _queue_ = _machine_["queue"]
    _gib_ = lambda _bytes_: f"{_bytes_ / 2**30:.1f}G" if isinstance(_bytes_, int) else "-"
    print(f"workers: memory {_gib_(_machine_['memory'].get('used'))} of {_gib_(_machine_['memory'].get('limit'))}; agents {_gib_(_machine_['agentsMemory'].get('used'))} of {_gib_(_machine_['agentsMemory'].get('limit'))}; stopped for memory: {_machine_['memoryStops']['count']}")
    print(f"queue: slots {_queue_['slots']['taken']}/{_queue_['slots']['total']}, waiting {_queue_['waiting']}, timing cores {'reserved' if _machine_['cpus'].get('timingReserved') else 'shared'}")
    print(f"{'WORKER':<34} {'ROLE':<13} {'STATE':<17} {'RUNS':<5} {'MEMORY':>7} {'TESTS':<10} {'AHEAD':>5} {'REVIEWS':<8} CLAIMED BY THE AGENT")
    for _worker_ in document["workers"]:
        _reviews_ = _worker_.get("reviews")
        _plain_ = "".join(_letter_ if _letter_.isprintable() else "?" for _letter_ in _worker_.get("claim", {}).get("value", ""))[:60]
        print(
            f"{_worker_['project'] + '/' + _worker_['branch'] + '/' + _worker_['name']:<34} {_worker_['role']:<13} {_worker_['state']['value']:<17} "
            f"{'yes' if _worker_['running']['value'] else 'no':<5} {_gib_(_worker_.get('memory', {}).get('used')):>7} {_worker_.get('acceptance', {}).get('value', '-'):<10} "
            f"{_worker_.get('commits', {}).get('ahead', '-'):>5} {(str(_reviews_['count']) + (' (' + str(_reviews_['outdated']) + ' old)' if _reviews_['outdated'] else '')) if _reviews_ else '-':<8} {_plain_}"
        )
    for _worker_, _command_, _task_ in commands:
        print(f"to start the next reviewer of {_worker_} (the manager writes its task file first: {_task_}):\n  {_command_}")


def main():
    _arguments_ = sys.argv[1:]
    if (len(_arguments_) < 2) or (_arguments_[0] != "--config"):
        print("usage: workers status [--json]", file=sys.stderr)
        sys.exit(2)
    _configPath_ = _arguments_[1]
    with open(_configPath_) as _file_:
        _status_ = Status(json.load(_file_))
    _status_.configPath = _configPath_
    _arguments_ = _arguments_[2:]
    # <project>/<branch>/<name>, for the two uses that name one worker
    _names_ = _arguments_[1].split("/") if (len(_arguments_) == 2) else []
    _named_ = (len(_names_) == 3) and all(NAME.fullmatch(_name_) for _name_ in _names_)
    if (len(_arguments_) >= 2) and (_arguments_[0] == "--refresh-commits") and all(NAME.fullmatch(_name_) for _name_ in _arguments_[1:]):
        _status_.refreshCommits(_arguments_[1:])
    elif (len(_arguments_) == 4) and (_arguments_[0] == "--full-run") and all(NAME.fullmatch(_name_) for _name_ in _arguments_[1:3]) and COMMIT.fullmatch(_arguments_[3]):
        print(_status_.fullRun(*_arguments_[1:]))
    elif _named_ and (_arguments_[0] == "--unmerged"):
        print(_status_.unmerged(*_names_))
    elif _named_ and (_arguments_[0] == "--forget"):
        _status_.forget(*_names_)
    elif (_arguments_ == ["--list"]):
        _status_.document()
        for _row_ in _status_.rows:
            print("\t".join(_row_))
    elif (_arguments_ == ["--reminder"]):
        _sentence_ = _status_.reminder()
        if _sentence_:
            print(_sentence_)
    elif (_arguments_ == ["--json"]):
        _status_.deferCounts = True
        print(json.dumps(_status_.document()))
    elif not _arguments_:
        _status_.deferCounts = True
        _document_ = _status_.document()
        table(_document_, _status_.commands)
    else:
        print("usage: workers status [--json]", file=sys.stderr)
        sys.exit(2)
    for _problem_ in _status_.problems:
        print(f"workers: {_problem_}", file=sys.stderr)


if (__name__ == "__main__"):
    main()
