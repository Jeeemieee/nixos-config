# Starts a program whose arguments name folders or files that an agent may have written: open-checked <program> <arguments...>
# Every `--ro-bind-checked <root> <path below it> <destination>` among the arguments is opened here, once, without following a link
# at any level below the root, and replaced by `--ro-bind-fd <descriptor> <destination>`: bwrap then mounts what was opened, whatever
# is put at that path afterwards. `--bind-checked` is the same for a mount that stays writable (`--bind-fd`)
# A path that is missing or reached through a link stops the start
# Used for the agent's sandbox and for every job's sandbox alike, so that both get the same mounts by the same rule
import os
import stat
import sys
from typing import Annotated

OPTIONS = {"--ro-bind-checked": "--ro-bind-fd", "--bind-checked": "--bind-fd"}


def refuse(
    message: Annotated[str, "Why the program was not started"],
):
    print(f"open-checked: {message}", file=sys.stderr)
    sys.exit(2)


def openBelow(
    root: Annotated[str, "A folder no agent can exchange"],
    path: Annotated[str, "A path below it, which an agent may have written"],
):
    """A descriptor of what is at the path now, reached without a link at any level"""
    _parts_ = [_part_ for _part_ in path.split("/") if _part_]
    if not _parts_ or any(_part_ in (".", "..") for _part_ in _parts_):
        refuse(f"{path} is not a path below {root}")
    try:
        _current_ = os.open(root, os.O_PATH | os.O_DIRECTORY)
        for _part_ in _parts_:
            _next_ = os.open(_part_, os.O_PATH | os.O_NOFOLLOW, dir_fd=_current_)
            os.close(_current_)
            _current_ = _next_
            # With O_PATH and O_NOFOLLOW a link is opened as itself: it is refused, not followed
            if stat.S_ISLNK(os.fstat(_current_).st_mode):
                raise OSError("a link")
    except OSError:
        refuse(f"{os.path.join(root, path)} is missing or is reached through a link, so the sandbox does not start")
    os.set_inheritable(_current_, True)
    return _current_


def main():
    if (len(sys.argv) < 2):
        refuse("usage: open-checked <program> <arguments...>")
    _arguments_ = sys.argv[2:]
    _result_ = []
    _index_ = 0
    while (_index_ < len(_arguments_)):
        if (_arguments_[_index_] in OPTIONS):
            if (_index_ + 3 >= len(_arguments_)):
                refuse(f"{_arguments_[_index_]} needs a root, a path below it and a destination")
            _descriptor_ = openBelow(_arguments_[_index_ + 1], _arguments_[_index_ + 2])
            _result_ += [OPTIONS[_arguments_[_index_]], str(_descriptor_), _arguments_[_index_ + 3]]
            _index_ += 4
        elif (_arguments_[_index_] == "--"):
            # What follows is the command inside the sandbox, not an option of the sandbox
            _result_ += _arguments_[_index_:]
            break
        else:
            _result_.append(_arguments_[_index_])
            _index_ += 1
    os.execvp(sys.argv[1], [sys.argv[1], *_result_])


if (__name__ == "__main__"):
    main()
