# Checks an implementer's intent form: intent-check [--json] <size limit in bytes> <file>
# The form is Markdown with fixed headings (workers/intent-template.md). A worker runs this inside its sandbox to see what is
# missing (`intent check`); `workers approve` runs the same program outside, on its own copy of the form, before the user is asked
# The form is an agent's text: it is only read, line by line, and nothing in it is run or used as a path
# Exit status: 0 the form is complete, 1 it is not, 2 it cannot be checked. With --json the findings are printed as one JSON
# object, also for a form that is not complete
import json
import re
import sys
from typing import Annotated

SECTIONS = ["Goal", "Changes", "Not changed", "Acceptance criteria", "Tests", "Recommendation", "Open questions"]
LISTS = ["Acceptance criteria", "Tests"]
PARTS = ["Trade-offs", "Steps"]
# The characters a test's name may have, as the project's test command takes it; it never starts like an option
TEST = re.compile(r"[A-Za-z0-9_./:\[\]@=,+][A-Za-z0-9_./:\[\]@=,+-]*")
APPROACH = re.compile(r"Approach\s+(\d+)\s*:(.*)")
ITEM = re.compile(r"\s*(?:[-*]|\d+[.)])\s+(\S.*)")


def sections(
    text: Annotated[str, "The form without its comments"],
):
    """The lines below each heading of the second level, and below each heading of the third level inside it"""
    _found_ = []
    _fenced_ = False
    for _line_ in text.split("\n"):
        # A heading inside a block of code is text
        if _line_.lstrip().startswith("```"):
            _fenced_ = not _fenced_
        if not _fenced_ and _line_.startswith("## "):
            _found_.append({"heading": " ".join(_line_[3:].split()), "lines": [], "parts": {}, "part": None})
        elif not _fenced_ and _line_.startswith("### ") and _found_:
            _found_[-1]["part"] = " ".join(_line_[4:].split())
            _found_[-1]["parts"].setdefault(_found_[-1]["part"], [])
        elif _found_:
            _target_ = _found_[-1]["parts"][_found_[-1]["part"]] if _found_[-1]["part"] else _found_[-1]["lines"]
            _target_.append(_line_)
    return _found_


def items(
    lines: Annotated[list, "The lines of a section"],
):
    return [_match_.group(1).strip() for _match_ in map(ITEM.fullmatch, lines) if _match_]


def check(
    content: Annotated[bytes, "The form as it was read"],
):
    """What is missing in the form, and what it says, for the one who approves it"""
    _problems_ = []
    _result_ = {"problems": _problems_, "approaches": [], "criteria": [], "tests": [], "newTests": []}
    try:
        _text_ = content.decode()
    except UnicodeDecodeError:
        _problems_.append("the form is not text in UTF-8")
        return _result_
    _found_ = sections(re.sub(r"<!--.*?-->", "", _text_, flags=re.DOTALL))

    ## Step 1. The fixed sections: each once, each with text, the lists with entries
    for _name_ in SECTIONS:
        _matching_ = [_section_ for _section_ in _found_ if (_section_["heading"] == _name_)]
        if (len(_matching_) != 1):
            _problems_.append(f"the heading '## {_name_}' is {'missing' if not _matching_ else 'there more than once'}")
        elif not "".join(_matching_[0]["lines"]).strip():
            _problems_.append(f"'## {_name_}' is empty")
        elif (_name_ in LISTS) and not items(_matching_[0]["lines"]):
            _problems_.append(f"'## {_name_}' needs a list: lines that start with '- '")
    _by_ = {_section_["heading"]: _section_ for _section_ in _found_}
    _result_["criteria"] = items(_by_.get("Acceptance criteria", {"lines": []})["lines"])

    ## Step 2. The approaches: two or more, each with a number of its own, a title, trade-offs and a list of steps
    for _section_ in _found_:
        _match_ = APPROACH.fullmatch(_section_["heading"])
        if not _match_:
            continue
        _number_, _title_ = int(_match_.group(1)), _match_.group(2).strip()
        _label_ = f"'## Approach {_number_}'"
        if any(_approach_["number"] == _number_ for _approach_ in _result_["approaches"]):
            _problems_.append(f"{_label_} is there more than once")
            continue
        if not _title_:
            _problems_.append(f"{_label_} has no title after the colon")
        if not "".join(_section_["parts"].get("Trade-offs", [])).strip():
            _problems_.append(f"{_label_} has no text below '### Trade-offs'")
        _steps_ = items(_section_["parts"].get("Steps", []))
        if not _steps_:
            _problems_.append(f"{_label_} has no list of steps below '### Steps'")
        _result_["approaches"].append({"number": _number_, "title": _title_, "steps": _steps_})
    if (len(_result_["approaches"]) < 2):
        _problems_.append(f"the form needs two or more approaches ('## Approach <number>: <title>'); it has {len(_result_['approaches'])}")

    ## Step 3. The recommendation names one of them
    _named_ = re.findall(r"[Aa]pproach\s+(\d+)", "\n".join(_by_.get("Recommendation", {"lines": []})["lines"]))
    _numbers_ = [_approach_["number"] for _approach_ in _result_["approaches"]]
    if _named_ and (int(_named_[0]) in _numbers_):
        _result_["recommended"] = int(_named_[0])
    elif ("Recommendation" in _by_):
        _problems_.append("'## Recommendation' names none of the approaches: write 'Approach <number>'")

    ## Step 4. The tests: existing ones by name with a reason, new ones with their expected result, or the reason why none fits
    _tests_ = items(_by_.get("Tests", {"lines": []})["lines"])
    for _entry_ in _tests_:
        _named_ = re.fullmatch(r"`([^`]*)`\s*:\s*(\S.*)", _entry_)
        _other_ = re.fullmatch(r"(new|none)\s*:\s*(\S.*)", _entry_)
        if _named_ and TEST.fullmatch(_named_.group(1)):
            _result_["tests"].append(_named_.group(1))
        elif _named_:
            _problems_.append(f"the test name `{_named_.group(1)[:80]}` is not one: letters, digits and _ . / : [ ] @ = , + -, without a space and not starting with '-'")
        elif _other_ and (_other_.group(1) == "new"):
            _result_["newTests"].append(_other_.group(2))
        elif _other_ and (len(_tests_) > 1):
            _problems_.append("'none:' in '## Tests' stands alone, without other tests")
        elif _other_:
            _result_["noTests"] = _other_.group(2)
        else:
            _problems_.append(f"a line of '## Tests' is '`<name>`: <reason>', 'new: <test and expected result>' or 'none: <reason>'; this one is not: {_entry_[:80]}")
    return _result_


def main():
    _arguments_ = sys.argv[1:]
    _asJson_ = bool(_arguments_) and (_arguments_[0] == "--json")
    if _asJson_:
        _arguments_.pop(0)
    if (len(_arguments_) != 2) or not _arguments_[0].isdigit():
        print("usage: intent-check [--json] <size limit in bytes> <file>", file=sys.stderr)
        sys.exit(2)
    _limit_ = int(_arguments_.pop(0))
    try:
        with open(_arguments_[0], "rb") as _file_:
            _content_ = _file_.read(_limit_ + 1)
    except OSError as _error_:
        print(f"intent-check: {_arguments_[0]} cannot be read: {_error_.strerror}", file=sys.stderr)
        sys.exit(2)
    if (len(_content_) > _limit_):
        print(f"intent-check: {_arguments_[0]} is larger than {_limit_} bytes", file=sys.stderr)
        sys.exit(2)
    _result_ = check(_content_)
    if _asJson_:
        print(json.dumps(_result_))
    elif _result_["problems"]:
        print(f"{_arguments_[0]} is not complete:")
        for _problem_ in _result_["problems"]:
            print(f"- {_problem_}")
    else:
        print(f"{_arguments_[0]} is complete: {len(_result_['approaches'])} approaches, {len(_result_['tests'])} existing and {len(_result_['newTests'])} new tests")
    sys.exit(1 if _result_["problems"] else 0)


if (__name__ == "__main__"):
    main()
