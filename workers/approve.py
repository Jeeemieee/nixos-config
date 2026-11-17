# The user's approval of an implementer's intent, outside every sandbox (see docs/WORKERS.md):
#   workers approve [--empty-scratch] <project>/<branch>/<name>   read the worker's form, choose an approach, type yes
#   workers approve --without-form <project>/<branch>/<name>      open the lock for a small task; also before the worker's first start
#   workers approve --revoke <project>/<branch>/<name>            close it again, from the worker's next start
# The approval is a record in the tools' state, which no sandbox can reach. Nothing that a worker writes opens the lock
# The form is an agent's text. It is copied once, without following a link and within a size limit; that one copy is checked,
# shown, fingerprinted and recorded, so what is approved is what was shown. What was decided goes into records/decision.md of
# the worker's folder, which the worker can read and not write
# Two more uses, by the tools themselves, so that one program reads and judges the records:
#   approve.py --state <worker>        for the launcher: open, no approval, or no baseline
#   approve.py --acceptance <worker>   for the queue's broker: which tests an acceptance run of this worker runs, and how
# The lock is open when the worker is approved and, if tests were approved with it, the broker's records hold a run of exactly
# those tests on the copy as it was when it was approved (the baseline)
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
import tomllib
from typing import Annotated

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
TEST = re.compile(r"[A-Za-z0-9_./:\[\]@=,+][A-Za-z0-9_./:\[\]@=,+-]*")
COMMIT = re.compile(r"[0-9a-f]{40,64}")
USAGE = "usage: workers approve [--without-form | --revoke | --empty-scratch] <project>/<branch>/<name>"
SHOWN = 4096
# Every line of the form is shown behind this, so that no line of an agent's text can pass for a line of this tool
QUOTE = "  | "


class Refused(Exception):
    """Why nothing was changed"""


def plain(
    text: Annotated[str, "Text that an agent wrote"],
    limit: Annotated[int, "The longest it is shown or written"] = SHOWN,
):
    """The text with every control character but the line break and the tab replaced, so that it can be shown and written down"""
    return "".join(_letter_ if (_letter_ in "\n\t") or (_letter_.isprintable()) else "?" for _letter_ in text[:limit])


def ask(
    question: Annotated[str, "What the user is asked"],
):
    print(question, end="", flush=True)
    _answer_ = sys.stdin.readline()
    if not _answer_:
        raise Refused("no answer: nothing was approved")
    return _answer_.rstrip("\n")


def write(
    path: Annotated[str, "A file in a folder that no agent writes"],
    text: Annotated[str, "Its content"],
    mode: Annotated[int, "Its permissions"],
):
    """A new file put in place by a rename, so that nobody reads half of it"""
    _new_ = f"{path}.new"
    if os.path.lexists(_new_):
        os.unlink(_new_)
    _file_ = os.open(_new_, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    os.write(_file_, text.encode())
    os.close(_file_)
    os.replace(_new_, path)


def digest(
    tests: Annotated[list, "Names of tests, in the order they were approved or proposed"],
):
    return hashlib.sha256("\n".join(tests).encode()).hexdigest()


class Worker:
    """One worker's records and folders, and what the tools read from them"""

    def __init__(
        self,
        config: Annotated[dict, "The programs and limits, from the system configuration"],
        name: Annotated[str, "<project>/<branch>/<name>"],
    ):
        _names_ = name.split("/")
        if (len(_names_) != 3) or not all(NAME.fullmatch(_part_) for _part_ in _names_):
            raise Refused(USAGE)
        self.config = config
        self.name = name
        self.project, self.branch, self.worker = _names_
        _home_ = os.environ["HOME"]
        self.state = os.path.join(_home_, ".local/state/workers", self.project)
        self.record = os.path.join(self.state, "approvals", self.branch, self.worker)
        self.folder = os.path.join(_home_, "workers", self.project, self.branch, self.worker)
        self.instructions = os.path.join(_home_, "workers", self.project, "instructions")
        self.decision = os.path.join(self.folder, "records", "decision.md")
        # A name's role is the one it was first started with
        self.role = self._word(os.path.join(self.state, "roles", self.branch, self.worker))
        # The project itself, which no agent writes
        self.main = self._word(os.path.join(self.state, "main"))

    def approval(self):
        """The approval's record, or nothing"""
        if not os.path.isfile(self.record):
            return None
        try:
            with open(self.record) as _file_:
                return json.load(_file_)
        except (OSError, ValueError) as _error_:
            raise Refused(f"the approval's record {self.record} cannot be read ({_error_}); take it back with: workers approve --revoke {self.name}")

    def form(self):
        """The worker's form as it is now: its bytes and what the check found in it; or the reason why it cannot be read"""
        _content_, _reason_ = self._copied(self.folder, "reports/intent.md")
        if _content_ is None:
            return None, None, _reason_
        _checked_ = subprocess.run([*self.config["intentCheck"], "--json", str(self.config["maxFormBytes"]), "/dev/stdin"], input=_content_, capture_output=True)
        if (_checked_.returncode not in (0, 1)):
            return None, None, _checked_.stderr.decode(errors="replace").strip()
        return _content_, json.loads(_checked_.stdout), None

    def task(self):
        """The task bytes used by approval, and the tests named directly below its fixed header"""
        _content_, _ = self._copied(self.instructions, f"{self.branch}/{self.worker}.md")
        _content_ = _content_ or b""
        _tests_ = []
        for _line_ in _content_.decode(errors="replace").split("\n")[3:]:
            if not _line_.startswith("test:"):
                break
            _test_ = _line_[len("test:") :].strip()
            if not TEST.fullmatch(_test_):
                raise Refused(f"the task file of {self.name} names a test that is not a test's name: {plain(_test_, 80)}")
            _tests_.append(_test_)
        return _content_, _tests_

    def added(self):
        """The tests that the manager added in the worker's task file"""
        return self.task()[1]

    def advice(
        self,
        formFingerprint: Annotated[str, "The sha256 fingerprint of the one form copy that will be shown"],
        taskFingerprint: Annotated[str, "The sha256 fingerprint of the task bytes used by approval"],
        testsCommit: Annotated[str, "The project branch commit that supplies the tests"],
    ):
        """Each manager's optional advice file, and whether it names all approval inputs"""
        _managerRoot_ = os.path.join(os.environ["HOME"], "workers", self.project, "manager")
        try:
            _names_ = sorted(os.listdir(_managerRoot_))
        except OSError:
            return []
        _found_ = []
        for _name_ in _names_:
            # Only a worker whose recorded role is manager can supply manager advice
            if not NAME.fullmatch(_name_) or (self._word(os.path.join(self.state, "roles", "manager", _name_)) != "manager"):
                continue
            _root_ = os.path.join(_managerRoot_, _name_)
            _path_ = f"reports/advice/{self.branch}/{self.worker}.md"
            if not os.path.lexists(os.path.join(_root_, _path_)):
                continue
            _content_, _reason_ = self._copied(_root_, _path_)
            if _content_ is None:
                _found_.append({"manager": _name_, "state": "unreadable", "reason": _reason_})
                continue
            _lines_ = _content_.decode(errors="replace").splitlines()
            _headers_ = [
                f"worker: {self.name}",
                f"form-sha256: {formFingerprint}",
                f"task-sha256: {taskFingerprint}",
                f"tests-commit: {testsCommit}",
            ]
            if (len(_lines_) < 4) or (_lines_[0] != _headers_[0]):
                _found_.append({"manager": _name_, "state": "other", "content": _content_})
                continue
            _reasons_ = []
            if (_lines_[1] != _headers_[1]):
                _reasons_.append("the form changed")
            if (_lines_[2] != _headers_[2]):
                _reasons_.append("the task changed")
            if (_lines_[3] != _headers_[3]):
                _reasons_.append("the project tests commit changed")
            if _reasons_:
                _found_.append({"manager": _name_, "state": "stale", "reasons": _reasons_, "content": _content_})
            else:
                _found_.append({"manager": _name_, "state": "current", "content": _content_})
        return _found_

    def mainBranch(self):
        """The branch of the project that only the user commits on"""
        return self._word(os.path.join(self.state, "main-branch")) or "main"

    def tip(
        self,
        branch: Annotated[str, "A branch of the project"],
    ):
        """The project's commit of a branch as it is now, asked without entering a repository; or nothing"""
        if not self.main:
            return None
        return self._remote(self.main, f"refs/heads/{branch}")

    def reference(self):
        """Which reference of the worker's copy stands for its work, for every tool: what is tested, approved against and called current"""
        # An implementer's own branch: the one its reviewers start from and the manager fetches, wherever the copy's files stand
        # now. Every other role has no branch of its own: what its copy has checked out
        return f"refs/heads/worker/{self.branch}/{self.worker}" if (self.role in (None, "implementer")) else "HEAD"

    def copy(self):
        """The commit of that reference, asked from outside with the copy as the remote: nothing in the copy runs"""
        return self._remote(f"file://{os.path.join(self.folder, 'repo')}", self.reference())

    def tested(self):
        """The same for an acceptance run, which needs one: the reference and its commit"""
        _commit_ = self.copy()
        if not _commit_:
            if (self.reference() == "HEAD"):
                raise Refused(f"the copy of {self.name} has no commit that could be tested")
            raise Refused(f"the copy of {self.name} has no branch {self.reference()[len('refs/heads/'):]}: that branch is what is tested, reviewed and merged, so there is nothing to run")
        return {"reference": self.reference(), "copyCommit": _commit_}

    def stated(
        self,
        commit: Annotated[str, "A commit of the project"],
    ):
        """How the project says its tests are run, in workers.toml at that commit of its own history; nothing if it has no such file"""
        # The project is written by no agent, so git may read it here
        _shown_ = subprocess.run([self.config["git"], "--git-dir", os.path.join(self.main, ".git"), "show", f"{commit}:workers.toml"], cwd="/", capture_output=True)
        if (_shown_.returncode != 0):
            return None
        _where_ = f"workers.toml of {self.main} at {commit[:10]}"
        try:
            _tests_ = tomllib.loads(_shown_.stdout.decode()).get("tests")
        except (ValueError, UnicodeDecodeError) as _error_:
            raise Refused(f"{_where_} cannot be read: {_error_}")
        if not isinstance(_tests_, dict):
            raise Refused(f"{_where_} has no [tests] table")
        for _key_ in ("paths", "all", "selected"):
            _value_ = _tests_.get(_key_)
            if not isinstance(_value_, list) or not _value_ or not all(isinstance(_word_, str) and _word_ for _word_ in _value_):
                raise Refused(f"{_where_}: [tests] needs '{_key_}', a list of words that is not empty")
        for _path_ in _tests_["paths"]:
            if _path_.startswith(("/", "-")) or (".." in _path_.split("/")):
                raise Refused(f"{_where_}: '{_path_}' in paths is not a path inside the project")
        return {_key_: _tests_[_key_] for _key_ in ("paths", "all", "selected")}

    def baseline(
        self,
        approval: Annotated[dict, "The approval's record"],
    ):
        """Whether the broker's records hold an acceptance run of the approved tests, on the copy as it was approved, that ran to its end"""
        try:
            with open(os.path.join(self.folder, "records", "runs.jsonl")) as _file_:
                _lines_ = _file_.readlines()
        except OSError:
            return False
        for _line_ in _lines_:
            try:
                _run_ = json.loads(_line_)
            except ValueError:
                continue
            # A run that was stopped, by its client or at a time limit, did not show what the tests say: it is no baseline
            if isinstance(_run_, dict) and (_run_.get("kind") == "acceptance") and ("exit" in _run_) and not _run_.get("stopped") and not _run_.get("time_limit"):
                if all(_run_.get(_key_) == approval.get(_other_) for _key_, _other_ in (("listDigest", "listDigest"), ("testsCommit", "testsCommit"), ("commit", "copyCommit"))):
                    return True
        return False

    def running(self):
        """Whether this worker's sandbox is active at this moment"""
        _unit_ = f"worker:{self.project}:{self.branch}:{self.worker}.scope"
        return subprocess.run([self.config["systemctl"], "--user", "is-active", "--quiet", _unit_], check=False).returncode == 0

    def requestRestart(
        self,
        approval: Annotated[dict, "The approval whose open lock is being acted on"],
    ):
        """Ask a supported real pi launcher to replace this sandbox once for this approval"""
        ## Step 1. Find the supported control channel of the running launcher
        _runtime_ = os.environ.get("XDG_RUNTIME_DIR")
        if not _runtime_:
            return False
        _unit_ = f"worker:{self.project}:{self.branch}:{self.worker}"
        _control_ = os.path.join(_runtime_, "workers", f"{_unit_}.control")
        try:
            _mode_ = os.open(os.path.join(_control_, "mode"), os.O_RDONLY | os.O_NOFOLLOW)
            _supported_ = os.read(_mode_, 32) == b"supported\n"
            os.close(_mode_)
        except OSError:
            return False
        if not _supported_:
            return False

        ## Step 2. Serialize the one request belonging to this approval
        _generation_ = approval.get("approvalId") or hashlib.sha256(json.dumps(approval, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _restartRoot_ = os.path.join(self.state, "continuations", self.branch)
        os.makedirs(_restartRoot_, mode=0o700, exist_ok=True)
        _marker_ = os.path.join(_restartRoot_, self.worker)
        _guard_ = os.open(f"{_marker_}.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(_guard_, fcntl.LOCK_EX)
            if (self._word(_marker_) == _generation_):
                return True

            ## Step 3. Reserve the one use, then publish it; a failed publication gives the use back
            write(_marker_, f"{_generation_}\n", 0o600)
            try:
                write(os.path.join(_control_, "restart"), json.dumps({"nonce": secrets.token_hex(16), "worker": self.name}) + "\n", 0o600)
            except OSError:
                if (self._word(_marker_) == _generation_):
                    os.unlink(_marker_)
                return False
            return True
        except OSError:
            return False
        finally:
            os.close(_guard_)

    def _word(
        self,
        path: Annotated[str, "A small file of the tools' state"],
    ):
        try:
            with open(path) as _file_:
                return _file_.read(4096).strip()
        except OSError:
            return None

    def _copied(
        self,
        root: Annotated[str, "A folder that no agent can exchange"],
        path: Annotated[str, "A file below it that an agent may have written"],
    ):
        """The file's bytes, read once without following a link and within the size limit; or the reason why not"""
        _runtime_ = os.path.join(os.environ["XDG_RUNTIME_DIR"], "workers")
        os.makedirs(_runtime_, mode=0o700, exist_ok=True)
        _copy_ = os.path.join(_runtime_, f"approve-{os.getpid()}.copy")
        try:
            _read_ = subprocess.run([*self.config["readChecked"], root, path, str(self.config["maxFormBytes"]), _copy_], capture_output=True, text=True)
            if (_read_.returncode != 0):
                return None, _read_.stderr.strip().replace("read-checked: ", "")
            with open(_copy_, "rb") as _file_:
                return _file_.read(), None
        finally:
            if os.path.exists(_copy_):
                os.unlink(_copy_)

    def _remote(
        self,
        remote: Annotated[str, "A repository"],
        reference: Annotated[str, "What is asked of it"],
    ):
        try:
            _answer_ = subprocess.run([self.config["git"], "ls-remote", remote, reference], cwd="/", capture_output=True, text=True, timeout=20).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return None
        return _answer_[0] if _answer_ and COMMIT.fullmatch(_answer_[0]) else None


def state(
    worker: Annotated[Worker, "An implementer"],
):
    """One word for the launcher: whether the worker's copy is writable at this start, and if not, what is missing"""
    _approval_ = worker.approval()
    if _approval_ is None:
        return "no approval"
    if _approval_.get("noTests") or worker.baseline(_approval_):
        return "open"
    return "no baseline"


def acceptance(
    worker: Annotated[Worker, "An implementer or a manager"],
):
    """What an acceptance run of this worker runs: the project's command, the tests, and the commit of the project they are taken from"""
    if (worker.role == "manager"):
        # The whole suite on the merged result, with the tests of the manager's copy itself; the command is the project's
        _commit_ = worker.tip(worker.mainBranch())
        _stated_ = worker.stated(_commit_) if _commit_ else None
        if _stated_ is None:
            raise Refused(f"the project of {worker.name} states no tests (no workers.toml on its main branch), so there is nothing to run")
        return {"list": "all", "tests": [], "listDigest": digest([]), "testsCommit": _commit_, "project": worker.main, "paths": [], "command": _stated_["all"], **worker.tested()}
    if (worker.role != "implementer"):
        raise Refused(f"{worker.name} is a {worker.role}: an acceptance run is an implementer's, and with --all a manager's")
    _approval_ = worker.approval()
    if _approval_ is not None:
        if _approval_.get("noTests"):
            raise Refused(f"{worker.name} was approved without tests ({_approval_['noTests']}), so there is nothing to run")
        _kind_, _tests_, _commit_ = "approved", _approval_["tests"], _approval_["testsCommit"]
    else:
        # Before the approval: the tests that the worker's form proposes, with the manager's, as they would be approved now
        _content_, _found_, _reason_ = worker.form()
        if _content_ is None:
            raise Refused(f"the form of {worker.name} cannot be read: {_reason_}")
        if _found_["problems"]:
            raise Refused("the form is not complete, so it proposes no tests to run yet; `intent check` says what is missing")
        _kind_, _tests_, _commit_ = "proposed", _found_["tests"] + [_test_ for _test_ in worker.added() if (_test_ not in _found_["tests"])], worker.tip(worker.branch)
    if not _tests_:
        raise Refused("the form proposes no existing test, so there is nothing to run")
    _stated_ = worker.stated(_commit_) if _commit_ else None
    if _stated_ is None:
        raise Refused(f"the project of {worker.name} states no tests (no workers.toml on its branch {worker.branch}), so there is nothing to run")
    # The tests' names follow the project's command
    return {"list": _kind_, "tests": _tests_, "listDigest": digest(_tests_), "testsCommit": _commit_, "project": worker.main, "paths": _stated_["paths"], "command": _stated_["selected"] + _tests_, **worker.tested()}


def show(
    worker: Annotated[Worker, "The worker whose form is shown"],
    content: Annotated[bytes, "The form as it was read"],
    advice: Annotated[list, "The managers' advice files and how they relate to this form"],
):
    """The form and current advice, every agent-written line behind a mark of this tool's"""
    _lines_ = plain(content.decode(errors="replace"), worker.config["maxFormBytes"]).split("\n")
    _shown_ = [f"The form of {worker.name} ({len(content)} bytes); every line of it stands behind '{QUOTE.strip()}':", *[QUOTE + _line_ for _line_ in _lines_], "The end of the form."]
    if not advice:
        _shown_.append("No manager advice for this form.")
    for _entry_ in advice:
        _manager_ = _entry_["manager"]
        if (_entry_["state"] == "current"):
            _adviceLines_ = plain(_entry_["content"].decode(errors="replace"), worker.config["maxFormBytes"]).split("\n")
            _shown_ += [f"Advice from manager {_manager_} (the manager's word; checked against this form, task and tests commit); every line stands behind '{QUOTE.strip()}':", *[QUOTE + _line_ for _line_ in _adviceLines_], f"The end of advice from manager {_manager_}."]
        elif (_entry_["state"] == "stale"):
            _reason_ = ", and ".join(_entry_["reasons"])
            _command_ = f"cd {shlex.quote(worker.main)} && pi --role manager --name {_manager_} -c"
            _shown_.append(f"Advice from manager {_manager_} is not current because {_reason_}. Start the manager again to renew it with: {_command_}")
        elif (_entry_["state"] == "other"):
            _shown_.append(f"Advice from manager {_manager_} does not have the exact worker, form-sha256, task-sha256 and tests-commit headers for {worker.name}, so it is not shown as current.")
        else:
            _shown_.append(f"Advice from manager {_manager_} cannot be read safely: {plain(_entry_['reason'], 300)}")
    _text_ = "\n".join(_shown_) + "\n"
    if sys.stdout.isatty():
        # As the commit guard shows a change: q closes the viewer, and the questions follow
        subprocess.run(worker.config["viewer"], input=_text_.encode(), check=False)
    else:
        print(_text_, end="")


def approve(
    worker: Annotated[Worker, "The worker that is approved"],
    arguments: Annotated[argparse.Namespace, "The command line"],
):
    ## Step 1. Only implementers have a lock
    if (worker.role not in (None, "implementer")) or (worker.branch in ("manager", "archive", "instructions", "plain", "old")):
        raise Refused(f"{worker.name} is a {worker.role or 'name no implementer can have'}: only an implementer's copy is locked until it is approved")
    _approval_ = worker.approval()

    ## Step 2. Close the lock again
    if arguments.revoke:
        if _approval_ is None:
            raise Refused(f"{worker.name} is not approved")
        os.unlink(worker.record)
        if os.path.isfile(worker.decision) and not os.path.islink(worker.decision):
            os.unlink(worker.decision)
        print(f"the approval of {worker.name} is taken back: from its next start its copy of the project is read-only again")
        return

    ## Step 3. A worker that is approved already: nothing is changed, and what holds is said
    if _approval_ is not None:
        _when_ = datetime.datetime.fromtimestamp(_approval_["time"]).strftime("%Y-%m-%d %H:%M")
        if _approval_.get("withoutForm"):
            print(f"{worker.name} was approved without a form on {_when_}")
        else:
            print(f"{worker.name} was approved on {_when_}: approach {_approval_['approach']}, {plain(_approval_['title'], 200)}")
            _content_, _, _reason_ = worker.form()
            if _content_ is None:
                print(f"its form cannot be read now: {_reason_}")
            elif (hashlib.sha256(_content_).hexdigest() == _approval_["fingerprint"]):
                print("its form is as it was approved")
            else:
                print("its form changed since approval")
        print({"open": "its copy is writable", "no baseline": "its copy stays read-only until the approved tests have run on it: queue acceptance, inside"}[state(worker)])
        raise Refused(f"nothing was changed; to approve it anew, take the approval back first: workers approve --revoke {worker.name}")

    ## Step 4. What is approved: nothing but the user's word, or one approach of the worker's form as it is now
    _approval_ = {"worker": worker.name, "approvalId": secrets.token_hex(16)}
    _lines_ = ["# Decision", "", f"Written by `workers approve` for {worker.name}. The worker can read this file and cannot change it.", ""]
    if arguments.without_form:
        if worker.role is None:
            print(f"there is no worker {worker.name} yet: its first start will find it approved")
        print(f"{worker.name} gets a copy of the project that it can write, without a written intent.")
        _approval_.update({"withoutForm": True, "tests": [], "noTests": "approved without a form"})
        _lines_ += ["- Approved without a form: the user opened the lock himself"]
    else:
        if (worker.role is None) or not os.path.isdir(os.path.join(worker.folder, "reports")):
            raise Refused(f"there is no implementer {worker.name} with a folder to read a form from; a small task without a form: workers approve --without-form {worker.name}")
        _content_, _found_, _reason_ = worker.form()
        if _content_ is None:
            raise Refused(f"the form of {worker.name} cannot be read: {_reason_}")
        if _found_["problems"]:
            print(f"the form of {worker.name} is not complete:", file=sys.stderr)
            for _problem_ in _found_["problems"]:
                print(f"- {plain(_problem_, 300)}", file=sys.stderr)
            raise Refused("nothing was approved; the worker sees the same list with: intent check")
        # The tests: the form's, then the ones the manager added in the task file; and whether the project says how to run them
        _taskContent_, _taskTests_ = worker.task()
        _added_ = [_test_ for _test_ in _taskTests_ if (_test_ not in _found_["tests"])]
        _tests_ = _found_["tests"] + _added_
        _commit_ = worker.tip(worker.branch)
        _stated_ = worker.stated(_commit_) if _commit_ else None
        _fingerprint_ = hashlib.sha256(_content_).hexdigest()
        _taskFingerprint_ = hashlib.sha256(_taskContent_).hexdigest()
        _advice_ = worker.advice(_fingerprint_, _taskFingerprint_, _commit_ or "")
        show(worker, _content_, _advice_)
        for _approach_ in _found_["approaches"]:
            _mark_ = "  (the worker's recommendation)" if (_approach_["number"] == _found_.get("recommended")) else ""
            print(f"Approach {_approach_['number']}: {plain(_approach_['title'], 200)}, {len(_approach_['steps'])} steps{_mark_}")
        print(f"Tests: {', '.join(_found_['tests']) or 'none that exists'}; new ones proposed: {len(_found_['newTests'])}")
        if _added_:
            print(f"Tests added by the manager in the task file: {', '.join(_added_)}")
        if _tests_ and _stated_ is None:
            print(f"The project states no tests (no workers.toml on its branch {worker.branch}): the approval alone will open the lock")
        _answer_ = ask("Which approach do you approve? Its number: ")
        _chosen_ = [_approach_ for _approach_ in _found_["approaches"] if (_answer_.strip() == str(_approach_["number"]))]
        if not _chosen_:
            raise Refused(f"'{plain(_answer_, 40)}' is not the number of an approach: nothing was approved")
        _approval_.update(
            {
                "approach": _chosen_[0]["number"],
                "title": _chosen_[0]["title"][:SHOWN],
                "steps": [_step_[:SHOWN] for _step_ in _chosen_[0]["steps"]],
                "tests": _tests_,
                "newTests": [_test_[:SHOWN] for _test_ in _found_["newTests"]],
                # Of the bytes that were shown above
                "fingerprint": _fingerprint_,
                # Which managers' advice was shown, checked against that same one copy of the form
                "advice": {
                    "shown": sorted(_entry_["manager"] for _entry_ in _advice_ if (_entry_["state"] == "current")),
                    "formFingerprint": _fingerprint_,
                    "taskFingerprint": _taskFingerprint_,
                    "testsCommit": _commit_,
                },
                # What a run of these tests must name to count as the baseline: the list, the project's commit that the tests
                # are taken from, and the commit the worker's copy is at now
                "listDigest": digest(_tests_),
            }
        )
        if _commit_:
            _approval_["testsCommit"] = _commit_
        _copy_ = worker.copy()
        if _copy_:
            _approval_["copyCommit"] = _copy_
        if not _tests_:
            _approval_["noTests"] = "no existing test was approved"
        elif _stated_ is None:
            _approval_["noTests"] = "the project states no tests"
        _lines_ += [f"- Approach {_chosen_[0]['number']}: {plain(_chosen_[0]['title'], 200)}", f"- The form's fingerprint (sha256): {_approval_['fingerprint']}"]
    _note_ = ask("A note of yours for the worker (may be empty): ")
    if (ask(f"Type yes to approve {worker.name}: ") != "yes"):
        raise Refused("not approved: nothing was changed")

    ## Step 5. With --empty-scratch: the scratch area as it was when the worker was made, before anything is recorded
    if arguments.empty_scratch:
        if not worker.config["helper"]:
            raise Refused("--empty-scratch needs the datasets: on this machine the scratch areas are plain folders. Nothing was approved")
        if worker.running():
            raise Refused(f"{worker.name} is running: end its session first. Nothing was approved")
        _emptied_ = subprocess.run([*worker.config["helper"], "rollback", worker.project, worker.branch, worker.worker, "created"], capture_output=True, text=True)
        if (_emptied_.returncode != 0):
            raise Refused(f"the scratch area of {worker.name} could not be emptied ({_emptied_.stderr.strip()}). Nothing was approved")
        print(f"the scratch area of {worker.name} is as it was when the worker was made: empty")

    ## Step 6. The record, which is the lock; then the decision file for the worker
    _approval_.update({"time": int(time.time()), "note": _note_[:SHOWN]})
    if ("advice" in _approval_):
        _adviceNames_ = ", ".join(_approval_["advice"]["shown"]) or "none"
        _lines_ += [
            f"- Manager advice shown: {_adviceNames_}",
            f"- The form fingerprint that advice was checked against (sha256): {_approval_['advice']['formFingerprint']}",
            f"- The task fingerprint that advice was checked against (sha256): {_approval_['advice']['taskFingerprint']}",
            f"- The project tests commit that advice was checked against: {_approval_['advice']['testsCommit']}",
        ]
    os.makedirs(os.path.dirname(worker.record), mode=0o700, exist_ok=True)
    write(worker.record, json.dumps(_approval_) + "\n", 0o600)
    _lines_ += [f"- Approved: {datetime.datetime.fromtimestamp(_approval_['time']).astimezone().isoformat(timespec='minutes')}", f"- The user's note: {plain(_note_) or '(none)'}"]
    if ("testsCommit" in _approval_) and not _approval_.get("noTests"):
        _lines_ += [f"- The project's commit that the tests are taken from: {_approval_['testsCommit']}"]
    if not arguments.without_form:
        _lines_ += ["", "## Steps, as approved", ""] + [f"- {plain(_step_)}" for _step_ in _approval_["steps"]]
        _lines_ += ["", "## Tests, as approved", ""] + [f"- `{_test_}`" for _test_ in _approval_["tests"]]
        if _approval_.get("noTests"):
            _lines_ += [f"No tests are run before and after the work: {_approval_['noTests']}."]
        if _approval_["newTests"]:
            _lines_ += ["", "## New tests that the worker proposed", ""] + [f"- {plain(_test_)}" for _test_ in _approval_["newTests"]]
    # The records folder is read-only in every sandbox of the worker, and the folder above it is in none
    _where_ = ""
    if os.path.isdir(os.path.dirname(worker.decision)) and not os.path.islink(os.path.dirname(worker.decision)):
        write(worker.decision, "\n".join(_lines_) + "\n", 0o644)
        _where_ = f"; what was decided is in {worker.decision}"
    _lockState_ = state(worker)
    if _approval_.get("noTests"):
        print(f"approved (no tests: {_approval_['noTests']}): from its next start {worker.name} can write its copy of the project{_where_}")
    elif (_lockState_ == "open"):
        print(f"approved, and the approved tests have run on its copy already: from its next start {worker.name} can write its copy of the project{_where_}")
    else:
        print(f"approved. Its copy stays read-only until the approved tests have run on it as it is, which is the baseline: the worker runs 'queue acceptance' and is started again{_where_}")
    _running_ = worker.running()
    _restart_ = _running_ and (_lockState_ == "open") and worker.requestRestart(_approval_)
    if _restart_:
        print(f"{worker.name} is still running; automatic continuation was requested. Its current answer and chat are saved before pi resumes in a writable sandbox")
    elif _running_:
        print(f"{worker.name} is still running: end its running session, then continue the same chat with: cd {shlex.quote(worker.main)} && pi --branch {worker.branch} --name {worker.worker} -c")


def main():
    _parser_ = argparse.ArgumentParser(prog="workers approve", add_help=False)
    _parser_.add_argument("--config", required=True)
    for _option_ in ("--without-form", "--revoke", "--empty-scratch", "--state", "--acceptance", "--request-restart"):
        _parser_.add_argument(_option_, action="store_true")
    _parser_.add_argument("worker", nargs="?", default="")
    try:
        _arguments_ = _parser_.parse_args()
    except SystemExit:
        print(f"workers: {USAGE}", file=sys.stderr)
        sys.exit(2)
    with open(_arguments_.config) as _file_:
        _config_ = json.load(_file_)
    try:
        if (sum([_arguments_.without_form, _arguments_.revoke, _arguments_.empty_scratch, _arguments_.state, _arguments_.acceptance, _arguments_.request_restart]) > 1):
            raise Refused(USAGE)
        _worker_ = Worker(_config_, _arguments_.worker)
        if _arguments_.state:
            print(state(_worker_))
        elif _arguments_.acceptance:
            print(json.dumps(acceptance(_worker_)))
        elif _arguments_.request_restart:
            _approval_ = _worker_.approval()
            if (_approval_ is not None) and (_worker_.running()) and (state(_worker_) == "open"):
                _worker_.requestRestart(_approval_)
        else:
            approve(_worker_, _arguments_)
    except Refused as _refusal_:
        print(f"workers: {_refusal_}", file=sys.stderr)
        sys.exit(2)


if (__name__ == "__main__"):
    main()
