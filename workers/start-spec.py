# Trusted persistent worker start specifications
import json
import os
import re
import shlex
import stat
import sys
from typing import Annotated

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
MAX_RECORD_BYTES = 1024 * 1024
ROLES = ("implementer", "reviewer", "deep-reviewer", "manager")
VALUE_OPTIONS = {
    "--provider",
    "--model",
    "--models",
    "--tools",
    "-t",
    "--exclude-tools",
    "-xt",
    "--thinking",
    "--extension",
    "-e",
    "--skill",
    "--prompt-template",
    "--theme",
    "--use-theme",
    "--tui-mode",
}
FLAG_OPTIONS = {
    "--no-tools",
    "-nt",
    "--no-builtin-tools",
    "-nbt",
    "--no-extensions",
    "-ne",
    "--no-mcp",
    "--no-skills",
    "-ns",
    "--no-prompt-templates",
    "-np",
    "--no-themes",
    "--no-context-files",
    "-nc",
    "--verbose",
    "--approve",
    "-a",
    "--no-approve",
    "-na",
    "--offline",
}
PRIVATE_VALUE_OPTIONS = {
    "--api-key",
    "--system-prompt",
    "--append-system-prompt",
    "--session-dir",
}
ONE_USE_VALUE_OPTIONS = {"--session", "--session-id", "--fork"}
ONE_USE_FLAG_OPTIONS = {"--continue", "-c", "--resume", "-r", "--no-session", "--print", "-p", "--export", "--list-models"}


class Refused(Exception):
    pass


def parseWorker(
    worker: Annotated[str, "A worker identifier as project/branch/name"],
):
    """The three checked components of a worker identifier"""
    _parts_ = worker.split("/")
    if (len(_parts_) != 3) or not all(NAME.fullmatch(_part_) for _part_ in _parts_):
        raise Refused(f"'{worker}' is not <project>/<branch>/<name>")
    return tuple(_parts_)


def recordPath(
    state: Annotated[str, "The trusted workers state root"],
    worker: Annotated[str, "A checked worker identifier"],
):
    """The persistent record path of one worker"""
    _project_, _branch_, _name_ = parseWorker(worker)
    return os.path.join(state, _project_, "start-specs", _branch_, f"{_name_}.json")


def rememberedOptions(
    arguments: Annotated[list, "The Pi arguments from one worker invocation"],
):
    """Safe repeatable Pi arguments and the option names deliberately omitted"""
    _kept_, _omitted_ = [], []
    _index_ = 0
    while (_index_ < len(arguments)):
        _argument_ = arguments[_index_]
        if (_argument_ == "--"):
            if ((_index_ + 1) < len(arguments)):
                _omitted_.append("initial prompt")
            break
        if (_argument_ in VALUE_OPTIONS):
            if ((_index_ + 1) >= len(arguments)):
                raise Refused(f"the Pi option {_argument_} has no value")
            _kept_ += [_argument_, arguments[_index_ + 1]]
            _index_ += 2
            continue
        if (_argument_ in FLAG_OPTIONS):
            _kept_.append(_argument_)
            _index_ += 1
            continue
        if (_argument_ == "--mode"):
            if ((_index_ + 1) >= len(arguments)):
                raise Refused("the Pi option --mode has no value")
            if (arguments[_index_ + 1] == "text"):
                _kept_ += [_argument_, arguments[_index_ + 1]]
            else:
                _omitted_.append(_argument_)
            _index_ += 2
            continue
        if (_argument_ in (PRIVATE_VALUE_OPTIONS | ONE_USE_VALUE_OPTIONS)):
            if ((_index_ + 1) >= len(arguments)):
                raise Refused(f"the Pi option {_argument_} has no value")
            _omitted_.append(_argument_)
            _index_ += 2
            continue
        if (_argument_ in ONE_USE_FLAG_OPTIONS):
            _omitted_.append(_argument_)
            _index_ += 1
            continue
        if _argument_.startswith("-"):
            _omitted_.append(f"{_argument_} and the arguments after it")
            break
        _omitted_.append("initial prompt")
        break
    return _kept_, _omitted_


def validateRecord(
    record: Annotated[object, "A decoded start specification"],
    worker: Annotated[str, "The identifier the record must describe"],
):
    """Return a normalized supported record or refuse it"""
    _project_, _branch_, _name_ = parseWorker(worker)
    if not isinstance(record, dict) or (record.get("version") != 1):
        raise Refused(f"the start specification for {worker} has an unsupported form")
    _expected_ = {
        "project": str,
        "role": str,
        "branch": str,
        "name": str,
        "reviewed": (str, type(None)),
        "shares": list,
        "options": list,
    }
    if not all(isinstance(record.get(_key_), _kind_) for _key_, _kind_ in _expected_.items()):
        raise Refused(f"the start specification for {worker} is incomplete")
    if (os.path.basename(record["project"]) != _project_) or (record["branch"] != _branch_) or (record["name"] != _name_):
        raise Refused(f"the start specification for {worker} names another worker")
    if (record["role"] not in ROLES):
        raise Refused(f"the start specification for {worker} has unknown role {record['role']}")
    if (record["role"] == "reviewer") != (record["reviewed"] is not None):
        raise Refused(f"the start specification for {worker} has an invalid reviewer target")
    if (record["reviewed"] is not None) and not NAME.fullmatch(record["reviewed"]):
        raise Refused(f"the start specification for {worker} has an invalid reviewer target")
    if not all(isinstance(_option_, str) for _option_ in record["options"]):
        raise Refused(f"the start specification for {worker} has invalid Pi options")
    _safeOptions_, _omittedOptions_ = rememberedOptions(record["options"])
    if (_safeOptions_ != record["options"]) or _omittedOptions_:
        raise Refused(f"the start specification for {worker} has unsafe Pi options")
    for _share_ in record["shares"]:
        if (
            not isinstance(_share_, dict)
            or (_share_.get("mode") not in ("ro", "rw"))
            or not isinstance(_share_.get("path"), str)
            or not os.path.isabs(_share_["path"])
        ):
            raise Refused(f"the start specification for {worker} has an invalid share")
    return record


def load(
    state: Annotated[str, "The trusted workers state root"],
    worker: Annotated[str, "A worker identifier"],
):
    """Read one regular bounded trusted specification without following a link"""
    _path_ = recordPath(state, worker)
    _descriptor_ = None
    try:
        _descriptor_ = os.open(_path_, os.O_RDONLY | os.O_NOFOLLOW)
        _status_ = os.fstat(_descriptor_)
        if not stat.S_ISREG(_status_.st_mode) or (_status_.st_size > MAX_RECORD_BYTES):
            raise Refused(f"the start specification for {worker} is not a bounded regular file")
        _content_ = b""
        while (len(_content_) <= MAX_RECORD_BYTES):
            _more_ = os.read(_descriptor_, min(65536, MAX_RECORD_BYTES + 1 - len(_content_)))
            if not _more_:
                break
            _content_ += _more_
        if (len(_content_) > MAX_RECORD_BYTES):
            raise Refused(f"the start specification for {worker} is too large")
        return validateRecord(json.loads(_content_), worker)
    except FileNotFoundError as _error_:
        raise Refused(f"there is no remembered start for {worker}; register it with pi --register-start") from _error_
    except (OSError, ValueError, RecursionError) as _error_:
        raise Refused(f"the start specification for {worker} cannot be read") from _error_
    finally:
        if (_descriptor_ is not None):
            os.close(_descriptor_)


def workerArguments(
    record: Annotated[dict, "A validated start specification"],
):
    """The exact wrapper and safe Pi arguments represented by a specification"""
    _arguments_ = ["--role", record["role"]]
    if (record["role"] != "manager"):
        _arguments_ += ["--branch", record["branch"]]
    _arguments_ += ["--name", record["name"]]
    if (record["reviewed"] is not None):
        _arguments_ += ["--of", record["reviewed"]]
    for _share_ in record["shares"]:
        _arguments_ += ["--allow" if (_share_["mode"] == "rw") else "--allow-ro", _share_["path"]]
    return _arguments_ + record["options"]


def shortCommand(
    worker: Annotated[str, "A worker identifier"],
):
    """The stable user command for one specification"""
    parseWorker(worker)
    return f"workers start {worker}"


def shellCommand(
    record: Annotated[dict, "A validated start specification"],
):
    """A safely quoted diagnostic long command"""
    return f"cd {shlex.quote(record['project'])} && {shlex.join(['pi', *workerArguments(record)])}"


def checkPaths(
    record: Annotated[dict, "A validated start specification"],
    worker: Annotated[str, "The worker named in a refusal"],
):
    """Refuse a missing or moved project or share before replay"""
    for _kind_, _path_ in [("project", record["project"])] + [("share", _share_["path"]) for _share_ in record["shares"]]:
        try:
            _actual_ = os.path.realpath(_path_, strict=True)
        except OSError as _error_:
            raise Refused(f"the remembered {_kind_} for {worker} is missing or moved: {_path_}") from _error_
        if (_actual_ != _path_):
            raise Refused(f"the remembered {_kind_} for {worker} moved: {_path_} now resolves to {_actual_}")


def writeSpecification(
    state: Annotated[str, "The trusted workers state root"],
    project: Annotated[str, "The canonical project realpath"],
    role: Annotated[str, "The worker role"],
    branch: Annotated[str, "The worker branch"],
    name: Annotated[str, "The worker name"],
    reviewed: Annotated[str | None, "The reviewed implementer, for a reviewer"],
    shares: Annotated[list, "The approved normalized shares"],
    arguments: Annotated[list, "The Pi arguments of this invocation"],
):
    """Validate and atomically persist one normalized specification"""
    _projectName_ = os.path.basename(project)
    _worker_ = f"{_projectName_}/{branch}/{name}"
    parseWorker(_worker_)
    if (role not in ROLES):
        raise Refused(f"unknown role {role}")
    if (role == "reviewer") != (reviewed is not None):
        raise Refused(f"the reviewer start for {_worker_} needs exactly one --of target")
    _options_, _omitted_ = rememberedOptions(arguments)
    _record_ = validateRecord(
        {
            "version": 1,
            "project": project,
            "role": role,
            "branch": branch,
            "name": name,
            "reviewed": reviewed,
            "shares": [{"mode": _mode_, "path": _path_} for _mode_, _path_ in shares],
            "options": _options_,
        },
        _worker_,
    )
    _path_ = recordPath(state, _worker_)
    _folder_ = os.path.dirname(_path_)
    os.makedirs(_folder_, mode=0o700, exist_ok=True)
    _temporary_ = f"{_path_}.tmp-{os.getpid()}"
    try:
        _descriptor_ = os.open(_temporary_, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(_descriptor_, "w", encoding="utf-8") as _file_:
            json.dump(_record_, _file_, sort_keys=True, separators=(",", ":"))
            _file_.write("\n")
            _file_.flush()
            os.fsync(_file_.fileno())
        os.replace(_temporary_, _path_)
    finally:
        try:
            os.unlink(_temporary_)
        except FileNotFoundError:
            pass
    return _worker_, _record_, _omitted_


def writeCommand(
    arguments: Annotated[list, "The write subcommand arguments"],
):
    """Decode the launcher's fixed write protocol"""
    if (len(arguments) < 9):
        raise Refused("the start specification writer received an incomplete request")
    _state_, _project_, _role_, _branch_, _name_, _reviewed_, _show_, _countText_ = arguments[:8]
    try:
        _count_ = int(_countText_)
    except ValueError as _error_:
        raise Refused("the start specification writer received an invalid share count") from _error_
    _shareEnd_ = 8 + (2 * _count_)
    if (_count_ < 0) or (_shareEnd_ >= len(arguments)) or (arguments[_shareEnd_] != "--"):
        raise Refused("the start specification writer received invalid shares")
    if (_show_ not in ("0", "1", "2")):
        raise Refused("the start specification writer received an invalid display mode")
    _shareWords_ = arguments[8:_shareEnd_]
    _shares_ = [(_shareWords_[_index_], _shareWords_[_index_ + 1]) for _index_ in range(0, len(_shareWords_), 2)]
    if not all((_mode_ in ("ro", "rw")) and os.path.isabs(_path_) for _mode_, _path_ in _shares_):
        raise Refused("the start specification writer received an invalid share")
    _worker_, _record_, _omitted_ = writeSpecification(
        _state_,
        _project_,
        _role_,
        _branch_,
        _name_,
        None if (_reviewed_ == "-") else _reviewed_,
        _shares_,
        arguments[_shareEnd_ + 1 :],
    )
    if (_show_ in ("1", "2")):
        for _option_ in _omitted_:
            print(f"start-spec: {_option_} is used only for this invocation and is not remembered", file=sys.stderr)
    if (_show_ == "1"):
        print(f"registered {_worker_}")
        print(shortCommand(_worker_))
        print(shellCommand(_record_))


def main(
    arguments: Annotated[list, "Command-line arguments without the program name"],
):
    """Dispatch the closed helper operations"""
    if not arguments:
        raise Refused("usage: start-spec write ... | command <state> <worker> | start <state> <launcher> <worker> [--continue]")
    if (arguments[0] == "write"):
        writeCommand(arguments[1:])
        return
    if (arguments[0] == "command") and (len(arguments) == 3):
        print(shellCommand(load(arguments[1], arguments[2])))
        return
    if (arguments[0] == "start") and (len(arguments) in (4, 5)):
        if (len(arguments) == 5) and (arguments[4] != "--continue"):
            raise Refused("the remembered start has an unknown replay option")
        _record_ = load(arguments[1], arguments[3])
        checkPaths(_record_, arguments[3])
        _continuation_ = ["-c"] if (len(arguments) == 5) else []
        os.chdir(_record_["project"])
        os.execv(arguments[2], [arguments[2], *workerArguments(_record_), *_continuation_])
    raise Refused("usage: start-spec write ... | command <state> <worker> | start <state> <launcher> <worker> [--continue]")


if (__name__ == "__main__"):
    try:
        main(sys.argv[1:])
    except Refused as _refusal_:
        print(f"start-spec: {_refusal_}", file=sys.stderr)
        raise SystemExit(2) from None
