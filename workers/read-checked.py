# Copies one file that an agent may have written, for the pi launcher: read-checked <root> <path below it> <limit> <destination> [<line>...]
# The file is opened once, without following a link at any level below the root and without waiting on a pipe; whether it is a
# regular file, its size and its content are all taken from that one descriptor, so it cannot be exchanged between the steps
# With lines given, the copy is made only if the file starts with exactly those lines
import os
import stat
import sys
from typing import Annotated


def refuse(
    message: Annotated[str, "Why no copy was made"],
):
    print(f"read-checked: {message}", file=sys.stderr)
    sys.exit(3)


def main():
    if (len(sys.argv) < 5):
        refuse("usage: read-checked <root> <path below it> <limit> <destination> [<line>...]")
    _root_, _path_, _limit_, _destination_ = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    _header_ = sys.argv[5:]
    _shown_ = os.path.join(_root_, _path_)

    ## Step 1. Walk down from the root, refusing a link at every level
    _parts_ = [_part_ for _part_ in _path_.split("/") if _part_]
    if not _parts_ or any(_part_ in (".", "..") for _part_ in _parts_):
        refuse(f"{_shown_} is not a path below {_root_}")
    try:
        _folder_ = os.open(_root_, os.O_RDONLY | os.O_DIRECTORY)
        for _part_ in _parts_[:-1]:
            _next_ = os.open(_part_, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=_folder_)
            os.close(_folder_)
            _folder_ = _next_
        # Without waiting: a pipe put in the file's place would otherwise hold the start for ever
        _file_ = os.open(_parts_[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=_folder_)
    except OSError:
        refuse(f"there is no file {_shown_} that is reached without a link")

    ## Step 2. Kind, size and content from the one descriptor
    _status_ = os.fstat(_file_)
    if not stat.S_ISREG(_status_.st_mode):
        refuse(f"{_shown_} is not a regular file")
    if (_status_.st_size > _limit_):
        refuse(f"{_shown_} is larger than {_limit_} bytes")
    _content_ = b""
    while (len(_content_) <= _limit_):
        _more_ = os.read(_file_, _limit_ + 1 - len(_content_))
        if not _more_:
            break
        _content_ += _more_
    if (len(_content_) > _limit_):
        refuse(f"{_shown_} is larger than {_limit_} bytes")
    if _header_:
        _lines_ = _content_.split(b"\n")[: len(_header_)]
        if (_lines_ != [_line_.encode() for _line_ in _header_]):
            refuse(f"{_shown_} does not start with the lines: {' / '.join(_header_)}")

    ## Step 3. The copy, new and private to the user
    # Put in place by a rename, as a new file: a sandbox that has the earlier copy mounted keeps the earlier copy
    _copy_ = os.open(_destination_ + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.write(_copy_, _content_)
    os.close(_copy_)
    os.replace(_destination_ + ".new", _destination_)


if (__name__ == "__main__"):
    main()
