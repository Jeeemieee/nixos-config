#!/usr/bin/env python3
"""The tests T2 to T8 of HANDOFF.md for workers-watch, with the readings fixed in PLAN.md section 6,
the tests R2 of the second round (PLAN-R2.md, section 5), and V1 to V6 of HANDOFF-R3.md.

  run.py --normal BIN --sanitized BIN [--commanded BIN] [--only T2,T4,V]

Prints one line per check, `ok` or `FAIL`, and ends with status 1 if any check failed.
Expected figures are computed here from the sample, never copied from the program's output.
"""

import argparse
import concurrent.futures
import copy
import fcntl
import json
import os
import pty
import random
import re
import select
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failed = []
ENVIRONMENT = dict(
    os.environ,
    TERM="xterm-256color",
    ASAN_OPTIONS="detect_leaks=1:abort_on_error=0",
    UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1",
)
SANITIZER_WORDS = re.compile(rb"AddressSanitizer|LeakSanitizer|UndefinedBehaviorSanitizer|runtime error:|==ERROR")
ESCAPE_SEQUENCE = re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[^\[\]]")
SHORT_ROLES = {"implementer": "impl", "reviewer": "rev", "deep-reviewer": "deep", "manager": "mgr", "plain": "plain"}

# Clears the screen, sets the window title, starts a hyperlink; then a C1 control, a carriage return, a backspace
# and a direction override. MARK and the words stay readable when the controls are replaced
HOSTILE = "MARK\x1b[2J\x1b]0;TITLE\x07\x1b]8;;http://example.invalid\x1b\\LINK\x1b]8;;\x1b\\\u009b2J\r\b\u202eEND"


def check(name, passed, detail=""):
    # A long detail is the evidence of a failure; a short one is a measured figure, shown either way
    shown = detail if (not passed or len(detail) < 400) else ""
    print(("ok   " if passed else "FAIL ") + name + (": " + shown if shown else ""), flush=True)
    if not passed:
        failed.append(name)
    return passed


#### Running the program


def once(binary, path, width=160, height=50, detail=None, extra=()):
    """One frame: the exit status, the frame as text and as bytes, and what went to the error stream."""
    command = [binary, "--once", "--width", str(width), "--height", str(height)]
    command += ["--file", path] if path else []
    command += ["--detail", str(detail)] if detail is not None else []
    result = subprocess.run(command + list(extra), capture_output=True, env=ENVIRONMENT, timeout=120)
    return result.returncode, result.stdout.decode("utf-8", "replace"), result.stdout, result.stderr


def validate(binary, path=None):
    """One validation: its exit status, output as text and bytes, and the error stream."""
    command = [binary, "--validate"] + (["--file", path] if path else [])
    result = subprocess.run(command, capture_output=True, env=ENVIRONMENT, timeout=120)
    return result.returncode, result.stdout.decode("utf-8", "replace"), result.stdout, result.stderr


def cleanRun(name, status, raw, errors):
    """What T4 asks of every run: status 0, no sanitizer report, no escape byte and no other control character."""
    text = raw.decode("utf-8", "replace")
    controls = [c for c in text if (ord(c) < 0x20 and c != "\n") or 0x7F <= ord(c) <= 0x9F or c == "\u202e"]
    problems = []
    if status != 0:
        problems.append(f"status {status}")
    if errors:
        problems.append("error stream: " + errors.decode("utf-8", "replace")[:300])
    if b"\x1b" in raw:
        problems.append("the byte 0x1b is in the output")
    if controls:
        problems.append(f"control characters in the output: {controls[:5]!r}")
    if "\ufffd" in text and raw.decode("utf-8", "ignore") != text:
        problems.append("the output is not valid UTF-8")
    if problems:
        check(name, False, "; ".join(problems))
    return not problems


class Terminal:
    """The live program in a pseudo-terminal: keys in, everything it writes out."""

    def __init__(self, command, columns, lines):
        self.controller, follower = pty.openpty()
        self.resize(columns, lines, tell=False)
        self.process = subprocess.Popen(
            command, stdin=follower, stdout=follower, stderr=follower, env=ENVIRONMENT, start_new_session=True
        )
        os.close(follower)
        self.output = b""

    def resize(self, columns, lines, tell=True):
        fcntl.ioctl(self.controller, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))
        if tell:
            # The process has no controlling terminal here, so the kernel does not tell it itself
            os.kill(self.process.pid, signal.SIGWINCH)

    def read(self, seconds):
        end = time.monotonic() + seconds
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            ready, _, _ = select.select([self.controller], [], [], left)
            if ready:
                try:
                    data = os.read(self.controller, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.output += data

    def plain(self, start=0):
        return ESCAPE_SEQUENCE.sub(b"", self.output[start:]).decode("utf-8", "replace")

    def waitFor(self, text, timeout, start=0):
        """The seconds until the text is on the screen, or None after the timeout."""
        begin = time.monotonic()
        while time.monotonic() - begin < timeout:
            if text in self.plain(start):
                return time.monotonic() - begin
            self.read(0.05)
        return None

    def send(self, keys, pause=0.4):
        mark = len(self.output)
        os.write(self.controller, keys.encode())
        self.read(pause)
        return mark

    def close(self):
        """Quits with the key, and returns the exit status; a process that does not end is killed."""
        os.write(self.controller, b"q")
        end = time.monotonic() + 15
        while self.process.poll() is None and time.monotonic() < end:
            self.read(0.1)
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
            return "did not end"
        self.read(0.1)
        os.close(self.controller)
        return self.process.returncode


#### The oracle: what the frame must show, computed from the document


def near(shown, expected, decimals):
    """A figure may differ by one in its last shown digit (PLAN.md section 6)."""
    return abs(float(shown) - expected) <= 10**-decimals + 1e-9


def headerTable(frame, title):
    """One of the header's small tables: its unit, and for every label the figures of its row, as they are written."""
    lines = frame.splitlines()[:4]
    starts = [match.start() for match in re.finditer(r"WORKERS|MEMORY|DISK|PROCESSORS|QUEUE|EXCLUSIVE", lines[0])]
    start = lines[0].find(title)
    end = min([other for other in starts if other > start], default=1000)
    unit = re.match(title + r" (\w+)", lines[0][start:end])
    rows = {}
    for line in lines[1:]:
        label = re.match(r"\s*([a-z]+)\s", line[start:end])
        if label:
            rows[label.group(1)] = re.findall(r"(?<![\w.])\d+(?:\.\d+)?", line[start:end])
    return (unit.group(1) if unit else ""), rows


def figuresMatch(shown, values, divisor=1.0):
    return len(shown) == len(values) and all(
        near(text, value / divisor, len(text.partition(".")[2])) for text, value in zip(shown, values))


def amountMatches(frame, title, label, amount):
    """Compares a row of a header table with an amount in bytes: now, the peak if it has one, the limit."""
    values = [amount["used"]] + ([amount["peak"]] if "peak" in amount else []) + [amount["limit"]]
    # The table names its unit once, in its title; the figures are compared in that unit
    names = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit, rows = headerTable(frame, title)
    return unit in names and figuresMatch(rows.get(label, []), values, 1024 ** names.index(unit))


def rowsByWorker(frame):
    """The row of every worker in a frame, found through the names of the groups: (project, branch, name) -> line."""
    rows = {}
    group = None
    for line in frame.splitlines():
        match = re.match(r"  (\S+) / (\S+)$", line)
        if match:
            group = match.groups()
        elif group and re.match(r"[> ] \S", line):
            rows[group + (line[2:].split()[0],)] = line
    return rows


def checkOverview(name, document, frame, width):
    rows = rowsByWorker(frame)
    missing = []
    for worker in document["workers"]:
        key = (worker["project"], worker["branch"], worker["name"])
        line = rows.get(key, "")
        # The mark of a running sandbox stands before the state; a sandbox that does not run has none
        running = "▶ " if worker["running"]["value"] else "  "
        wanted = rf"^[> ] {re.escape(worker['name'])}\s+{SHORT_ROLES[worker['role']]}\s+{running}{worker['state']['value']}\s"
        if not re.search(wanted, line):
            missing.append("/".join(key) + " name, role, state, running mark")
            continue
        steps = worker.get("steps")
        if width >= 160 and worker["role"] == "implementer" and steps:
            # Plain text has no colour, so a claimed value carries its mark there
            if f"~{steps['done']}/{steps['total']} " not in line:
                missing.append("/".join(key) + " steps")
            if "current" in steps and f"~{steps['current']} " not in line:
                missing.append("/".join(key) + " to-do item")
    check(f"{name}: every worker's name, role and state; the steps and the to-do item of the implementers",
          not missing, ", ".join(missing))
    return rows


def testT2(binary, label):
    path = os.path.join(ROOT, "samples", "normal.json")
    document = json.load(open(path))
    status, frame, raw, errors = once(binary, path, 160, 50)
    if not cleanRun(f"T2 {label}", status, raw, errors):
        return
    workers = document["workers"]
    check(f"T2 {label}: the sample has three projects, all roles and all states",
          len({w["project"] for w in workers}) == 3 and len({w["role"] for w in workers}) == 5
          and len({w["state"]["value"] for w in workers}) == 8)
    rows = checkOverview(f"T2 {label}", document, frame, 160)
    check(f"T2 {label}: a frame of a fixed document does not depend on the clock", once(binary, path, 160, 50)[2] == raw)

    # The header: the queue, and the memory against its totals with the peak
    machine = document["machine"]
    lines = frame.splitlines()
    queue = machine["queue"]
    taken = headerTable(frame, "QUEUE")[1]
    processors = headerTable(frame, "PROCESSORS")[1]
    wrong = [name for name in ("slots", "parallel", "timing")
             if not figuresMatch(taken.get(name, []), [queue[name]["taken"], queue[name]["total"]])]
    wrong += [text for text in (f"{queue['waiting']} waiting", "timing cores 0-3 not reserved",
                                f"stopped {machine['memoryStops']['count']}×") if text not in frame]
    if not figuresMatch(processors.get("agents", []), [machine["agentsCpu"]["share"], machine["agentsCpu"]["limit"]]):
        wrong.append("the agents' processors")
    check(f"T2 {label}: the queue, the timing cores, the stops and the agents' processors in the header", not wrong, str(wrong))
    check(f"T2 {label}: the workers' and the agents' memory, now, peak and limit",
          amountMatches(frame, "MEMORY", "workers", machine["memory"]) and amountMatches(frame, "MEMORY", "agents", machine["agentsMemory"]),
          str(headerTable(frame, "MEMORY")))
    check(f"T2 {label}: the disk use of the two trees",
          amountMatches(frame, "DISK", "workers", machine["disk"]["workers"]) and amountMatches(frame, "DISK", "scratch", machine["disk"]["scratch"]),
          str(headerTable(frame, "DISK")))
    heads = next((line for line in lines if "IN WORK" in line and "CHANGED" in line), "")
    todo = heads.find("CHANGED") - 2 - heads.find("IN WORK")
    check(f"T2 {label}: the to-do column has at least 50 characters at 160 columns", todo >= 50, f"{todo}")

    # The detail of one worker: the whole to-do list with the step in work marked
    order = sorted(workers, key=lambda w: (w["project"], w["branch"], w["name"]))
    index, worker = next((i, w) for i, w in enumerate(order) if w["jobs"] and w.get("steps"))
    status, detail, raw, errors = once(binary, path, 160, 50, detail=index)
    if cleanRun(f"T2 {label} detail", status, raw, errors):
        marks = {"done": "✓ ", "in work": "▶ ", "open": "  "}
        items = [f"{marks[item['state']]}~{item['text']}" for item in worker["steps"]["items"]]
        check(f"T2 {label}: the detail shows the whole to-do list with the current step marked, the jobs and the claim",
              all(item in detail for item in items) and f"~{worker['jobs'][0]['command']}" in detail
              and f"~{worker['claim']['value']}" in detail and "intent" in detail and "commits" in detail)
        stops = worker["memoryStops"]["count"]
        row = rows.get((worker["project"], worker["branch"], worker["name"]), "")
        check(f"T2 {label}: a worker that was stopped for memory shows the count in its row and in its detail",
              f"✕{stops}" in row and f"stopped {stops}×" in detail.split("THE SYSTEM MEASURED")[-1], row)


def testT3(binary, label):
    path = os.path.join(ROOT, "samples", "normal.json")
    document = json.load(open(path))
    status, frame, raw, errors = once(binary, path, 80, 24)
    if not cleanRun(f"T3 {label}", status, raw, errors):
        return
    lines = frame.splitlines()
    longest = max(len(line) for line in lines)
    check(f"T3 {label}: no line is longer than 80, and there are 24 lines", longest <= 80 and len(lines) == 24,
          f"longest {longest}, lines {len(lines)}")
    checkOverview(f"T3 {label}", document, frame, 80)


#### T4: documents that are wrong or hostile


def paths(node, path=""):
    """Every value of a document with the name the program gives its field."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from paths(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from paths(value, f"{path}[{index}]")


def replaced(document, path, value):
    """A copy of the document with the value at a path replaced."""
    result = copy.deepcopy(document)
    parts = re.findall(r"[^.\[\]]+", path)
    node = result
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    node[int(last) if isinstance(node, list) else last] = value
    return result


def kind(value):
    for types, name in (((bool,), "flag"), ((int, float), "number"), ((str,), "text"), ((list,), "list"), ((dict,), "object")):
        if isinstance(value, types):
            return name
    return "null"


def wrongTypeMutations(sample):
    """The wrong-type documents of T4, each with the field path expected in its problem."""
    wrong = {"text": "wrong", "number": 7, "null": None, "list": [1], "object": {"wrong": 1}, "flag": True}
    mutations = []
    chosen = ["version", "generated", "machine", "workers", "workers[0]", "workers[1]", "workers[7]"]
    for path, value in paths(sample):
        if not any(path == start or path.startswith(start + ".") or path.startswith(start + "[") for start in chosen):
            continue
        if path.startswith("workers[") and not re.match(r"workers\[(0|1|7)\]", path):
            continue
        for name, substitute in wrong.items():
            # A number where a flag stands is a wrong type; a flag is never right elsewhere either
            if name != kind(value) and path:
                mutations.append((path, name, substitute))
    return mutations


def testT4(binary, scratch):
    sample = json.load(open(os.path.join(ROOT, "samples", "normal.json")))
    text = json.dumps(sample)
    counter = [0]

    def run(content, expected, name, detail=None, width=160):
        """Writes one document, shows it, and checks the run and the line that must say what is wrong."""
        counter[0] += 1
        path = os.path.join(scratch, f"t4-{counter[0]}.json")
        with open(path, "wb") as file:
            file.write(content if isinstance(content, bytes) else content.encode())
        status, frame, raw, errors = once(binary, path, width, 50, detail)
        os.remove(path)
        if not cleanRun(name, status, raw, errors):
            return None
        longest = max(len(line) for line in frame.splitlines())
        if longest > width:
            check(name, False, f"a line of {longest} characters")
            return None
        if not all(re.search(pattern, frame) for pattern in expected):
            check(name, False, f"expected {expected} in the frame:\n" + "\n".join(frame.splitlines()[:8]))
            return None
        return frame

    # The row of a worker of the sample in the overview, which is ordered by project, branch and name
    order = sorted(range(len(sample["workers"])), key=lambda i: [sample["workers"][i][k] for k in ("project", "branch", "name")])

    # Step 1. Whole documents that are wrong
    deepList = "[" * 10000 + "]" * 10000
    deepValue = '{"version":1,"workers":[],"machine":{"memory":' + '{"a":' * 10000 + "1" + "}" * 10000 + "}}"
    megabyte = "x" * 1_000_000
    cases = [
        ("an empty file", b"", [r"Unreadable: the document is empty"]),
        ("truncated JSON", text[: len(text) // 2], [r"Unreadable: the document is not valid JSON"]),
        ("an array instead of an object", "[1, 2, 3]", [r"Unreadable: the document is an array, expected an object"]),
        ("version 2", json.dumps(dict(sample, version=2)), [r"Problems \(1\): version is 2, this program reads version 1", "alpha"]),
        ("missing machine", json.dumps({k: v for k, v in sample.items() if k != "machine"}), [r"Problems \(1\): machine is missing", "alpha"]),
        ("missing workers", json.dumps({k: v for k, v in sample.items() if k != "workers"}), [r"Problems \(1\): workers is missing", r"slots +1 +5"]),
        ("a nesting depth of 10 000, arrays", deepList, [r"Unreadable: the document is an array, expected an object"]),
        ("a nesting depth of 10 000, inside a field", deepValue, [r"nested deeper than 32 levels"]),
        ("a string of 1 MB as a claim", json.dumps(replaced(sample, "workers[0].claim.value", megabyte)), ["alpha"]),
        ("a string of 1 MB as a to-do item", json.dumps(replaced(sample, "workers[0].steps.current", megabyte)), [r"~x{20,}…"]),
        ("a string of 1 MB as a name", json.dumps(replaced(sample, "workers[0].name", megabyte)), [r"xxxx…"]),
        ("a string of 1 MB as the whole document", json.dumps(megabyte), [r"Unreadable: the document is a string, expected an object"]),
        ("invalid UTF-8", text.encode().replace(b"alpha", b"al\xff\xfepha", 1), [r"Unreadable: the document is not valid JSON.*UTF-8"]),
        ("an overlong UTF-8 form", text.encode().replace(b"alpha", b"al\xc0\xafpha", 1), [r"Unreadable: the document is not valid JSON.*UTF-8"]),
        ("an unpaired surrogate escape", text.replace("alpha", "al\\udc80pha", 1), [r"Unreadable: the document is not valid JSON"]),
        ("the escape character, not escaped", text.encode().replace(b"alpha", b"al\x1b[2Jpha", 1), [r"Unreadable: the document is not valid JSON"]),
        ("a file of zero bytes only", b"\x00" * 4096, [r"Unreadable: the document is not valid JSON"]),
    ]
    results = [run(content, expected, "T4 " + name) for name, content, expected in cases]
    for width in (80, 160):
        results.append(run(json.dumps(replaced(sample, "workers[0].claim.value", megabyte)), [r"~x{20,}…"],
                           "T4 a string of 1 MB as a claim, in the detail", detail=order.index(0), width=width))
    check(f"T4 wrong documents: {len(results)} runs, each with status 0, no sanitizer report, no control character, and a line that says what is wrong",
          all(result is not None for result in results))

    # Step 2. Wrong types in every field in turn: the machine and the three workers that together have every field
    mutations = wrongTypeMutations(sample)
    seen = {re.sub(r"\[\d+\]", "[]", path) for path, _, _ in mutations}

    def mutate(mutation):
        path, name, substitute = mutation
        expected = r"Problems \(1\): " + re.escape(path) + r" is "
        return run(json.dumps(replaced(sample, path, substitute)), [expected], f"T4 {path} as {name}") is not None

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        results = list(pool.map(mutate, mutations))
    check(f"T4 wrong types: {len(results)} runs over {len(seen)} fields, each names the field that is wrong",
          all(results) and len(seen) > 90, f"{results.count(False)} failed")

    # Step 3. An unknown source is named and shown as claimed
    results = [run(json.dumps(replaced(sample, "workers[0].state.source", "trusted")),
                   [r"workers\[0\]\.state\.source is 'trusted', which is not a known source", r"~implementing"],
                   "T4 an unknown source")]

    # Step 4. The escape sequences in every text field: all at once, and one field at a time
    textPaths = [path for path, value in paths(sample) if isinstance(value, str)]
    everywhere = copy.deepcopy(sample)
    for path in textPaths:
        everywhere = replaced(everywhere, path, HOSTILE if not path.endswith("source") else "claimed\x1b[2J")
    document = json.dumps(everywhere)
    shown = [r"MARK�\[2J�\]0;TITLE�"]
    results.append(run(document, shown + [r"LINK�\]8;;"], "T4 escape sequences in every text field, overview", width=200) is not None)
    results.append(run(document, shown, "T4 escape sequences in every text field, overview at 160") is not None)
    results.append(run(document, [r"MARK�\[2J�\]0;TITL"], "T4 escape sequences in every text field, overview at 80", width=80) is not None)
    for index in range(len(sample["workers"])):
        results.append(run(document, shown + [r"jobs"], f"T4 escape sequences in every text field, detail {index}", detail=index) is not None)

    def inject(path):
        # The overview and the detail of every row are drawn: one of them must show the text, with its controls replaced
        changed = replaced(sample, path, HOSTILE)
        last = re.match(r"workers\[(\d+)\]\.lastQueuedRun", path)
        if last:
            # The last run is drawn only for a worker whose document has no list of runs
            changed["workers"][int(last.group(1))].pop("runs", None)
        hostile = json.dumps(changed)
        name = f"T4 escape sequences in {path}"
        frames = [run(hostile, [], name)] + [run(hostile, [], name, detail=index) for index in range(len(sample["workers"]))]
        if None in frames:
            return False
        # The state of a to-do item is drawn as a mark, and one that is not known as a question mark
        wanted = "? ~" if re.search(r"items\[\d+\]\.state$", path) else "MARK�"
        return any(wanted in frame for frame in frames) or check(name, False, "the text is in no frame")

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        results += list(pool.map(inject, textPaths))
    check(f"T4 escape sequences: {len(textPaths)} text fields, all at once and each in turn, in the overview and in every detail; "
          "the byte 0x1b is never in the output and the text is shown with the controls replaced", all(results))

    # Step 5. Beyond the handoff's list: documents with a few bytes changed, removed or repeated at random
    rng = random.Random(4)
    source = json.dumps(everywhere, ensure_ascii=False).encode()

    def damaged(number):
        content = bytearray(source if number % 2 else text.encode())
        for _ in range(rng.randint(1, 8)):
            position = rng.randrange(len(content))
            choice = rng.randrange(4)
            if choice == 0:
                content[position] = rng.randrange(256)
            elif choice == 1:
                del content[position:position + rng.randint(1, 40)]
            elif choice == 2:
                content[position:position] = bytes(rng.choices(b'{}[]",:\\\x1b\xff\x00 0-eE.tfn', k=rng.randint(1, 6)))
            else:
                content[position:position] = content[position:position + rng.randint(1, 200)]
        return bytes(content)

    documents = [damaged(number) for number in range(1500)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        results = list(pool.map(lambda pair: run(pair[1], [], f"T4 damaged document {pair[0]}", detail=pair[0] % 12 if pair[0] % 3 else None),
                                enumerate(documents)))
    check(f"T4 extra: {len(results)} documents damaged at random (seed 4), each with status 0, no sanitizer report and no control character",
          all(result is not None for result in results))

    # Step 6. The comparison the handoff asks for: a clean sample writes no escape byte either
    status, _, raw, errors = once(binary, os.path.join(ROOT, "samples", "normal.json"))
    check("T4 the clean sample writes the byte 0x1b 0 times, as every hostile one", status == 0 and b"\x1b" not in raw and not errors)
    return document


#### T5: the live program in a pseudo-terminal


def sequenceKinds(output):
    """The kinds of escape sequences in what the program wrote: colours as one kind, the others with their numbers."""
    kinds = set()
    for sequence in ESCAPE_SEQUENCE.findall(output):
        if sequence.startswith(b"\x1b[") and sequence.endswith(b"m"):
            kinds.add("colour or style")
        elif sequence.startswith(b"\x1b[") and sequence[-1:] in b"ABCDGHJK":
            kinds.add("cursor or erase " + sequence[-1:].decode())
        elif sequence.startswith(b"\x1b]"):
            kinds.add("operating system command " + sequence[2:12].decode("ascii", "replace"))
        else:
            kinds.add(sequence.decode("ascii", "replace"))
    return kinds


def liveSession(binary, path, name):
    """Start, move down, open and close a detail, sort, filter, resize, quit; what was on the screen at each step."""
    terminal = Terminal([binary, "--file", path, "--interval", "1"], 160, 50)
    origin = os.path.basename(path)
    seen = {}
    seen["start"] = terminal.waitFor("IN WORK", 20) is not None
    mark = terminal.send("\x1b[B\x1b[Bj")
    seen["move down"] = terminal.waitFor("> ", 5, mark) is not None
    mark = terminal.send("\r")
    seen["open the detail"] = terminal.waitFor("THE SYSTEM MEASURED", 5, mark) is not None
    mark = terminal.send("\x1b[B\x1b[C\x1b[D\x1b[6~\x1b[5~")
    mark = terminal.send("\x1b", pause=1.0)
    seen["close the detail"] = terminal.waitFor("IN WORK", 5, mark) is not None
    mark = terminal.send("?")
    seen["the list of keys"] = terminal.waitFor("any key closes this list", 5, mark) is not None
    mark = terminal.send("?")
    seen["close the list of keys"] = terminal.waitFor("IN WORK", 5, mark) is not None
    mark = terminal.send("s")
    seen["sort"] = terminal.waitFor("sorted by role", 5, mark) is not None
    mark = terminal.send("s")
    seen["sort again"] = terminal.waitFor("sorted by state", 5, mark) is not None
    mark = terminal.send("r")
    seen["filter by role"] = terminal.waitFor("only role ", 5, mark) is not None
    mark = terminal.send("ptb")
    seen["filter by project, state, branch"] = terminal.waitFor("only project ", 5, mark) is not None
    mark = terminal.send("x")
    seen["clear the filters"] = terminal.waitFor("sorted by state · " + origin, 5, mark) is not None
    mark = len(terminal.output)
    terminal.resize(80, 24)
    seen["resize to 80 by 24"] = terminal.waitFor("MEMORY", 5, mark) is not None
    mark = len(terminal.output)
    terminal.resize(60, 20)
    seen["resize below the smallest"] = terminal.waitFor("needs a window of 80 by 24", 5, mark) is not None
    mark = len(terminal.output)
    terminal.resize(200, 60)
    seen["resize to 200 by 60"] = terminal.waitFor("SCRATCH", 5, mark) is not None
    terminal.send("\x1b[6~\x1b[5~\x1b[F\x1b[H\r")
    status = terminal.close()
    report = SANITIZER_WORDS.search(terminal.output)
    missing = [step for step, passed in seen.items() if not passed]
    check(f"{name}: start, move, detail, sort, filter, resize, quit; status 0 and no sanitizer report",
          status == 0 and not report and not missing,
          f"status {status}, missing {missing}, report {terminal.output[report.start():report.start() + 400] if report else None}")
    return terminal.output


def testT5(binary, scratch, hostileDocument):
    clean = liveSession(binary, os.path.join(ROOT, "samples", "normal.json"), "T5 the live program")
    path = os.path.join(scratch, "hostile.json")
    with open(path, "w") as file:
        file.write(hostileDocument)
    hostile = liveSession(binary, path, "T5 the live program on the hostile sample")
    extra = sequenceKinds(hostile) - sequenceKinds(clean)
    check("T5 the hostile sample adds no kind of escape sequence to those of the clean run", not extra,
          f"{sorted(extra)}; the clean run has {sorted(sequenceKinds(clean))}")
    check("T5 no title, hyperlink or other operating system command is ever written",
          b"\x1b]" not in hostile and b"\x1b]" not in clean and b"TITLE\x07" not in hostile)
    # Beyond the handoff's list: random keys and sizes while the document changes between whole, hostile and broken
    rng = random.Random(6)
    sample = open(os.path.join(ROOT, "samples", "normal.json")).read()
    contents = [sample, hostileDocument, sample[: len(sample) // 3], json.dumps(dict(json.loads(sample), workers=[])), "[]"]
    terminal = Terminal([binary, "--file", path, "--interval", "1"], 160, 50)
    terminal.waitFor("IN WORK", 20)
    keys = ["\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D", "\x1b[5~", "\x1b[6~", "\x1b[H", "\x1b[F", "\r", "\x1b", "j", "k", "s", "p", "b", "r", "t", "x", "z", "\t", "?"]
    for step in range(400):
        if step % 25 == 0:
            with open(path, "w") as file:
                file.write(rng.choice(contents))
        if step % 40 == 0:
            terminal.resize(rng.randint(20, 220), rng.randint(5, 70))
        terminal.send(rng.choice(keys), pause=0.03)
    status = terminal.close()
    report = SANITIZER_WORDS.search(terminal.output)
    check("T5 extra: 400 random keys and 10 random sizes (seed 6) over a changing document; status 0 and no sanitizer report",
          status == 0 and not report and b"\x1b]" not in terminal.output,
          f"status {status}, report {terminal.output[report.start():report.start() + 600] if report else None}")
    check("T5 the hostile text is on the live screen with its controls replaced",
          "MARK�[2J�]0;TITLE�" in ESCAPE_SEQUENCE.sub(b"", hostile).decode("utf-8", "replace"))
    # A control of the comparison itself: it must notice a title sequence, were one written
    check("T5 control: the comparison notices a title sequence added to the clean run's output",
          bool(sequenceKinds(clean + b"\x1b]0;TITLE\x07") - sequenceKinds(clean)))


#### T6 to T8


def generator():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    # The tests leave nothing behind beside the sources
    sys.dont_write_bytecode = True
    import generate

    return generate


def highWater(pid):
    """The highest resident size of a running process so far, in KiB."""
    for line in open(f"/proc/{pid}/status"):
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    return 0


def testT6(binary, scratch):
    generate = generator()
    world = generate.newWorld(3, 300, 1794650000)
    path = os.path.join(scratch, "large.json")
    with open(path, "w") as file:
        json.dump(generate.document(world), file)
    size = os.path.getsize(path)

    # Step 1. The whole process of one frame, which is more than the frame alone
    times = []
    command = [binary, "--once", "--file", path, "--width", "160", "--height", "50"]
    for _ in range(20):
        begin = time.perf_counter()
        subprocess.run(command, stdout=subprocess.DEVNULL, env=ENVIRONMENT, check=True)
        times.append((time.perf_counter() - begin) * 1000)
    median = statistics.median(times)
    # The handoff's 50 ms is for the frame; a loaded machine must not fail the check, so the bound is five times that
    check("T6 one frame of 300 workers: reported, and failed only beyond 250 ms",
          median < 250, f"median of 20 whole runs {median:.1f} ms (fastest {min(times):.1f}, slowest {max(times):.1f}); the document has {size} bytes")

    # Step 2. Its memory: the frame is larger than the smallest pipe, so the process waits in its last write,
    # with all its work done, and its own highest resident size can be read; what the system reports for a
    # child after its end would include the memory of this test, which started it
    resident = 0
    for _ in range(3):
        reading, writing = os.pipe()
        fcntl.fcntl(writing, fcntl.F_SETPIPE_SZ, 4096)
        process = subprocess.Popen(command, stdout=writing, env=ENVIRONMENT)
        os.close(writing)
        time.sleep(0.5)
        resident = max(resident, highWater(process.pid))
        while os.read(reading, 65536):
            pass
        os.close(reading)
        process.wait()
    check("T6 the resident memory of one frame stays below 50 MiB", 0 < resident < 50 * 1024, f"{resident / 1024:.1f} MiB")

    # Step 3. The live program for 10 seconds, with keys in between
    terminal = Terminal([binary, "--file", path, "--interval", "1"], 160, 50)
    terminal.waitFor("IN WORK", 20)
    for keys in ("\x1b[6~", "\x1b[6~", "\r", "\x1b[C", "\r", "s", "r", "x", "\x1b[F"):
        terminal.send(keys, pause=1.0)
    terminal.read(1.0)
    highest = highWater(terminal.process.pid)
    status = terminal.close()
    check("T6 the resident memory of the live program stays below 50 MiB over 10 s",
          status == 0 and 0 < highest < 50 * 1024, f"{highest / 1024:.1f} MiB, status {status}")


def testT7(normal, commanded, scratch):
    # Step 1. The sources and the samples, searched for calls that start a process or write a file
    starts = re.compile(r"\b(system|popen|fork|vfork|posix_spawnp?|exec[lv]p?e?|execvpe|clone|daemon)\s*\(")
    writes = re.compile(r"\b(ofstream|fstream|fopen|freopen|creat|mkstemp|tmpfile|rename|unlink|remove|mkdir|truncate|"
                        r"ftruncate|pwrite|fwrite|fputs|fprintf|write)\s*[(<]|O_WRONLY|O_RDWR|O_CREAT|O_APPEND|O_TRUNC")
    found = {"starts": [], "writes": []}
    files = [os.path.join(ROOT, "CMakeLists.txt")]
    for folder in ("src", "samples"):
        files += [os.path.join(ROOT, folder, name) for name in sorted(os.listdir(os.path.join(ROOT, folder)))]
    for path in files:
        for number, line in enumerate(open(path, encoding="utf-8"), 1):
            code = line.split("//")[0]
            for name, pattern in (("starts", starts), ("writes", writes)):
                if pattern.search(code):
                    found[name].append(f"{os.path.relpath(path, ROOT)}:{number}: {line.strip()}")
    check("T7 exactly one call starts a process: posix_spawn in src/source.cpp, with the command of the build",
          len(found["starts"]) == 1 and "src/source.cpp" in found["starts"][0]
          and "::posix_spawn(&child, statusCommand[0]" in found["starts"][0], str(found["starts"]))
    check(f"T7 no call in {len(files)} files of the sources and the samples writes a file", not found["writes"], str(found["writes"]))

    # Step 2. The build without a command cannot start a process at all, and refuses to run without --file
    # The functions a program takes from the system's library, by `nm`. (The first version of this test searched
    # the program's bytes for the names, and so took a word of the help text, "system", for the function.)
    def imported(binary):
        listing = subprocess.run(["nm", "-D", "--undefined-only", binary], capture_output=True, text=True, check=True).stdout
        return {line.split()[-1].split("@")[0] for line in listing.splitlines() if line.strip()}

    calls = {"posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execl", "execlp", "popen", "fork", "vfork", "system", "clone"}
    names = calls & imported(normal)
    check("T7 the normal build does not even link a call that starts a process", not names and len(imported(normal)) > 20, str(names))
    result = subprocess.run([normal, "--once"], capture_output=True, env=ENVIRONMENT)
    check("T7 without a status command and without --file it refuses and says what to do",
          result.returncode == 2 and b"this build has no status command; give --file PATH" in result.stderr)

    # Step 3. A frame leaves the folder it runs in and its document as they were
    folder = os.path.join(scratch, "empty")
    os.mkdir(folder)
    sample = os.path.join(ROOT, "samples", "normal.json")
    before = (os.stat(sample).st_mtime_ns, open(sample, "rb").read())
    subprocess.run([normal, "--once", "--file", sample], capture_output=True, cwd=folder, env=dict(ENVIRONMENT, HOME=folder, TMPDIR=folder))
    check("T7 a run writes no file into its folder, its home or its temporary folder, and leaves the document alone",
          os.listdir(folder) == [] and before == (os.stat(sample).st_mtime_ns, open(sample, "rb").read()))

    # Step 4. The build with a stand-in command reads the document from it, and says when it fails
    if not commanded:
        print("skip T7 the build with a command: no --commanded given")
        return
    check("T7 control: the same search finds the call in the build with a command",
          calls & imported(commanded) == {"posix_spawn"}, str(calls & imported(commanded)))
    status, frame, raw, errors = once(commanded, None)
    check("T7 the build with a command shows the document that the command printed",
          cleanRun("T7 the build with a command", status, raw, errors) and "status command" in frame and "alpha / solver" in frame)
    ENVIRONMENT["WORKERS_WATCH_TEST_FAIL"] = "1"
    status, frame, raw, errors = once(commanded, None)
    del ENVIRONMENT["WORKERS_WATCH_TEST_FAIL"]
    check("T7 a command that fails is reported with its status and its first line, cleaned",
          cleanRun("T7 a failing command", status, raw, errors)
          and "Unreadable: the status command failed with status 3: the stand-in was told to fail �[2J" in frame, frame[:800])


def testT8(binary, scratch):
    generate = generator()
    world = generate.newWorld(5, 12, int(time.time()))
    path = os.path.join(scratch, "changing.json")

    def write(waiting, part=1.0):
        document = generate.document(world)
        document["machine"]["queue"]["waiting"] = waiting
        content = json.dumps(document)
        # In place, as a redirection would write it
        with open(path, "w") as file:
            file.write(content[: int(len(content) * part)])

    # Step 1. A changed document is on the screen within the refresh time
    write(41)
    terminal = Terminal([binary, "--file", path, "--interval", "1"], 160, 50)
    started = terminal.waitFor("41 waiting", 20) is not None
    delays = []
    for waiting in (42, 43, 44):
        generate.advance(world, 1)
        mark = len(terminal.output)
        write(waiting)
        delays.append(terminal.waitFor(f"{waiting} waiting", 5, mark))
    check("T8 the frame follows a changed file within 2 s at an interval of 1 s",
          started and all(delay is not None and delay <= 2.0 for delay in delays),
          "delays in s: " + ", ".join("none" if delay is None else f"{delay:.2f}" for delay in delays))

    # Step 2. Half a document does not end it: it says so and keeps the last readable one
    mark = len(terminal.output)
    write(45, part=0.5)
    noticed = terminal.waitFor("the document is not valid JSON", 5, mark)
    kept = "Unreadable, so the last readable document is shown: the document is not valid JSON" in terminal.plain(mark)
    alive = terminal.process.poll() is None
    mark = len(terminal.output)
    write(46)
    followed = terminal.waitFor("46 waiting", 5, mark)
    check("T8 a half-written file does not end it; it names the problem, keeps the last document, and follows the next one",
          noticed is not None and kept and alive and followed is not None, f"noticed {noticed}, kept {kept}, alive {alive}, followed {followed}")

    # Step 3. A file that disappears and comes back
    mark = len(terminal.output)
    os.remove(path)
    gone = terminal.waitFor("Unreadable, so the last readable document is shown: cannot read " + path, 5, mark)
    mark = len(terminal.output)
    write(47)
    back = terminal.waitFor("47 waiting", 5, mark)
    status = terminal.close()
    check("T8 a file that disappears is reported, and followed again when it is back; status 0 at the end",
          gone is not None and back is not None and status == 0, f"gone {gone}, back {back}, status {status}")

    # Step 4. The generator itself, writing every half second. The screen no longer shows the document's age;
    # a document that stays fresh is one that is never called overdue or unreadable while new frames keep coming
    writer = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "generate.py"), "--out", path, "--interval", "0.5"])
    time.sleep(1.0)
    terminal = Terminal([binary, "--file", path, "--interval", "1"], 160, 50)
    started = terminal.waitFor("IN WORK", 20) is not None
    mark = len(terminal.output)
    terminal.read(5.0)
    frames = terminal.plain(mark).count("IN WORK")
    stale = [word for word in ("Overdue", "Unreadable") if word in terminal.plain()]
    status = terminal.close()
    writer.send_signal(signal.SIGINT)
    writer.wait(10)
    check("T8 with the generator writing every half second the program runs on, and the document on the screen stays fresh",
          started and status == 0 and frames >= 3 and not stale, f"{frames} new frames in 5 s, {stale}, status {status}")


#### The second round: the agent's words without marks, an unchanged document, a quick end


def styleAt(output, text):
    """The looks in force where a text is written to the terminal: dim, italic, bold, inverted, colour."""
    position = output.find(text.encode())
    if position < 0:
        return None
    names = {1: "bold", 2: "dim", 3: "italic", 7: "inverted"}
    ends = {22: {"bold", "dim"}, 23: {"italic"}, 27: {"inverted"}, 39: {"colour"}}
    active = set()
    for sequence in re.finditer(rb"\x1b\[([0-9;]*)m", output[:position]):
        codes = [int(code) for code in sequence.group(1).split(b";") if code] or [0]
        index = 0
        while index < len(codes):
            code = codes[index]
            if code == 0:
                active.clear()
            elif code in names:
                active.add(names[code])
            elif code in ends:
                active -= ends[code]
            elif 30 <= code <= 37 or 90 <= code <= 97 or code == 38:
                active.add("colour")
            if code in (38, 48):
                # The colour's own numbers follow: 5 and one number, or 2 and three
                index += 2 if codes[index + 1:index + 2] == [5] else 4
            index += 1
    return active


def coloursIn(output):
    """The codes of all colours that were written, of the text and of its background."""
    found = set()
    for sequence in re.finditer(rb"\x1b\[([0-9;]*)m", output):
        for code in (int(code) for code in sequence.group(1).split(b";") if code):
            if 30 <= code <= 38 or 40 <= code <= 48 or 90 <= code <= 97 or 100 <= code <= 107:
                found.add(code)
    return found


def testR2(normal, commanded, scratch):
    sample = os.path.join(ROOT, "samples", "normal.json")
    document = json.load(open(sample))
    todo = document["workers"][0]["steps"]["current"]

    # Step 1. With colour the agent's own words are dim and italic and carry no mark; a measured value is neither
    ENVIRONMENT.pop("NO_COLOR", None)
    terminal = Terminal([normal, "--file", sample], 160, 50)
    terminal.waitFor("IN WORK", 20)
    terminal.read(0.5)
    status = terminal.close()
    words, state, label = (styleAt(terminal.output, text) for text in (todo, "implementing", "slots"))
    check("R2 with colour, a claimed text is dim and italic and has no mark; a derived state and a measured figure are not italic",
          status == 0 and words is not None and {"dim", "italic"} <= words and ("~" + todo) not in terminal.plain()
          and "italic" not in state and "italic" not in label and coloursIn(terminal.output),
          f"claimed {words}, state {state}, label {label}")

    # Step 2. Without colour the same text carries its mark, and no colour is written at all
    ENVIRONMENT["NO_COLOR"] = "1"
    terminal = Terminal([normal, "--file", sample], 160, 50)
    terminal.waitFor("IN WORK", 20)
    terminal.read(0.5)
    status = terminal.close()
    del ENVIRONMENT["NO_COLOR"]
    check("R2 with NO_COLOR, a claimed text carries the mark ~ and no colour is written",
          status == 0 and ("~" + todo) in terminal.plain() and not coloursIn(terminal.output), f"colours {sorted(coloursIn(terminal.output))}")

    # Step 3. A document that does not change is not drawn again: no byte in 10 s after the first frame.
    # The sample is of a fixed time long ago, so it is overdue from the first frame on
    terminal = Terminal([normal, "--file", sample, "--interval", "2"], 160, 50)
    overdue = terminal.waitFor("Overdue: the newest document is of ", 20) is not None
    terminal.read(3.0)
    mark = len(terminal.output)
    terminal.read(10.0)
    written = len(terminal.output) - mark
    status = terminal.close()
    check("R2 an unchanged document: 0 bytes are written in 10 s after the first frame", overdue and status == 0 and written == 0,
          f"{written} bytes, overdue line {overdue}, status {status}")

    # Step 4. A fresh document: one more frame when it becomes overdue, none for a file that was only touched,
    # one for a file that changed
    generate = generator()
    fresh = generate.document(generate.newWorld(5, 12, int(time.time())))
    path = os.path.join(scratch, "fresh.json")
    with open(path, "w") as file:
        json.dump(fresh, file)
    terminal = Terminal([normal, "--file", path, "--interval", "1"], 160, 50)
    terminal.waitFor("IN WORK", 20)
    terminal.read(8.0)
    # Frames with the document in them; the frame before the first document was read has none
    frames = terminal.plain().count("alpha / solver")
    late = "Overdue: the newest document is of " in terminal.plain()
    mark = len(terminal.output)
    os.utime(path)
    terminal.read(4.0)
    touched = len(terminal.output) - mark
    fresh["machine"]["queue"]["waiting"] = 77
    with open(path, "w") as file:
        json.dump(fresh, file)
    followed = terminal.waitFor("77 waiting", 4, mark)
    status = terminal.close()
    check("R2 a fresh document: one frame, one more when it becomes overdue; none when the file is only touched; one when it changes",
          frames == 2 and late and touched == 0 and followed is not None and status == 0,
          f"{frames} frames with the document in 8 s, overdue line {late}, {touched} bytes after the touch, followed after {followed} s, status {status}")

    # Step 5. q ends the program at once, also while the status command runs, and the command ends with it
    if not commanded:
        print("skip R2 the quick end: no --commanded given")
        return
    ENVIRONMENT["WORKERS_WATCH_TEST_SLOW"] = "1"
    terminal = Terminal([commanded, "--interval", "1"], 160, 50)
    terminal.read(2.0)
    del ENVIRONMENT["WORKERS_WATCH_TEST_SLOW"]

    def parentAndGroup(pid):
        try:
            fields = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
            return int(fields[1]), int(fields[2])
        except (OSError, ValueError, IndexError):
            return None, None

    # The status command is the program's only child, and the leader of a group of its own
    pids = [pid for pid in os.listdir("/proc") if pid.isdigit()]
    commands = [int(pid) for pid in pids if parentAndGroup(pid) == (terminal.process.pid, int(pid))]
    begin = time.monotonic()
    status = terminal.close()
    elapsed = time.monotonic() - begin
    time.sleep(0.2)
    left = [pid for pid in os.listdir("/proc") if pid.isdigit() and parentAndGroup(pid)[1] in commands]
    check("R2 q ends the program within 1 s while the status command runs, and nothing of the command is left",
          status == 0 and elapsed <= 1.0 and len(commands) == 1 and not left,
          f"{elapsed:.2f} s, status {status}, the command ran as {commands}, left of its group {left}")


#### The third round: one-shot validation by the dashboard's reader


def validationIsPlain(name, status, raw, errors, expectedStatus, report=True):
    """Checks the common contract of --validate and returns its non-empty lines."""
    text = raw.decode("utf-8", "replace")
    controls = [character for character in text if (ord(character) < 0x20 and character != "\n")
                or 0x7F <= ord(character) <= 0x9F or character == "\u202e"]
    passed = status == expectedStatus and not errors and b"\x1b" not in raw and not controls
    detail = f"status {status}, stderr {errors[:200]!r}, controls {controls[:5]!r}, output {text[:300]!r}"
    if report:
        check(name, passed, detail)
    return passed, [line for line in text.splitlines() if line], detail


def testV(normal, sanitized, commanded, scratch):
    samplePath = os.path.join(ROOT, "samples", "normal.json")
    sample = json.load(open(samplePath))

    # V1. Both a fixed sample and an independently generated document have no problem
    generate = generator()
    generatedPath = os.path.join(scratch, "generated.json")
    with open(generatedPath, "w") as file:
        json.dump(generate.document(generate.newWorld(4, 37, 1794650000)), file)
    for binary, label in ((normal, "normal sample"), (sanitized, "sanitized sample"),
                          (normal, "generated document"), (sanitized, "sanitized generated document")):
        path = samplePath if "sample" in label else generatedPath
        status, _, raw, errors = validate(binary, path)
        plain, lines, _ = validationIsPlain("V1 " + label, status, raw, errors, 0)
        check("V1 " + label + " writes no output", plain and not lines and not raw, raw[:300].decode("utf-8", "replace"))
    if commanded:
        status, _, raw, errors = validate(commanded)
        plain, lines, _ = validationIsPlain("V1 the build with a status command", status, raw, errors, 0)
        check("V1 the build with a status command writes no output", plain and not lines and not raw,
              raw[:300].decode("utf-8", "replace"))

    def writeDocument(name, document):
        path = os.path.join(scratch, name + ".json")
        with open(path, "w") as file:
            json.dump(document, file)
        return path

    # V2. Every wrong-type document used by T4 is readable and names its field, as do another version and no machine
    cases = [(path, replaced(sample, path, substitute)) for path, _, substitute in wrongTypeMutations(sample)]
    cases += [("version", dict(sample, version=2)),
              ("machine", {key: value for key, value in sample.items() if key != "machine"})]

    def wrongCase(numberAndCase):
        number, (field, document) = numberAndCase
        path = writeDocument(f"v2-{number}", document)
        status, text, raw, errors = validate(normal, path)
        plain, lines, detail = validationIsPlain(f"V2 {field} ({number})", status, raw, errors, 1, report=False)
        return plain and len(lines) >= 1 and any(field in line for line in lines), detail + "; " + text[:300]

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        results = list(pool.map(wrongCase, enumerate(cases)))
    missing = [detail for passed, detail in results if not passed]
    check(f"V2 {len(cases)} readable wrong documents each return status 1 and name the field", not missing,
          "\n".join(missing[:5]))

    # V3. A document that cannot be read at all has status 2 and exactly one line
    unreadable = [("no file", None), ("empty", b""), ("truncated", json.dumps(sample).encode()[:100]),
                  ("20 MiB", b" " * (20 * 1024 * 1024))]
    for label, content in unreadable:
        path = os.path.join(scratch, "v3-" + label.replace(" ", "-") + ".json")
        if content is not None:
            with open(path, "wb") as file:
                file.write(content)
        status, _, raw, errors = validate(normal, path)
        plain, lines, _ = validationIsPlain("V3 " + label, status, raw, errors, 2)
        check("V3 " + label + " writes one line", plain and len(lines) == 1, repr(lines))

    # V4. The schema's uniqueness, null and list limits are validation failures
    duplicate = copy.deepcopy(sample)
    duplicate["workers"].append(copy.deepcopy(sample["workers"][0]))
    nullValue = copy.deepcopy(sample)
    nullValue["workers"][0]["lastRun"] = None
    tooManyJobs = copy.deepcopy(sample)
    tooManyJobs["workers"][0]["jobs"] = [copy.deepcopy(sample["workers"][0]["jobs"][0]) for _ in range(21)]
    strict = [
        ("duplicate worker", duplicate, ("workers[12]", "project, branch and name")),
        ("null", nullValue, ("workers[0].lastRun", "null")),
        ("21 jobs", tooManyJobs, ("workers[0].jobs", "21 entries")),
    ]
    for number, (label, document, wanted) in enumerate(strict):
        status, text, raw, errors = validate(normal, writeDocument(f"v4-{number}", document))
        plain, lines, _ = validationIsPlain("V4 " + label, status, raw, errors, 1)
        check("V4 " + label + " is named", plain and len(lines) >= 1 and all(part in text for part in wanted), repr(lines))

    # V5. Text from a reported field is cleaned before it becomes a validation line
    hostile = replaced(sample, "workers[0].state.source", HOSTILE)
    status, text, raw, errors = validate(normal, writeDocument("v5-hostile", hostile))
    plain, lines, _ = validationIsPlain("V5 hostile source", status, raw, errors, 1)
    check("V5 the field and its cleaned text are in the line, with no escape byte",
          plain and len(lines) == 1 and "workers[0].state.source" in text and "MARK�[2J�]0;TITLE�" in text and b"\x1b" not in raw,
          repr(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--normal", required=True, help="the normal build of workers-watch")
    parser.add_argument("--sanitized", required=True, help="the build with the sanitizers")
    parser.add_argument("--commanded", help="a normal build with the stand-in status command")
    parser.add_argument("--only", default="T2,T3,T4,T5,T6,T7,T8,R2,V")
    arguments = parser.parse_args()
    only = arguments.only.split(",")
    for name in ("normal", "sanitized", "commanded"):
        if getattr(arguments, name):
            setattr(arguments, name, os.path.abspath(getattr(arguments, name)))

    with tempfile.TemporaryDirectory() as scratch:
        if "T2" in only:
            testT2(arguments.normal, "normal build")
            testT2(arguments.sanitized, "sanitized build")
        if "T3" in only:
            testT3(arguments.normal, "normal build")
            testT3(arguments.sanitized, "sanitized build")
        hostile = None
        if "T4" in only or "T5" in only:
            hostile = testT4(arguments.sanitized, scratch)
        if "T5" in only:
            testT5(arguments.sanitized, scratch, hostile)
        if "T6" in only:
            testT6(arguments.normal, scratch)
        if "T7" in only:
            testT7(arguments.normal, arguments.commanded, scratch)
        if "T8" in only:
            testT8(arguments.normal, scratch)
        if "R2" in only:
            testR2(arguments.normal, arguments.commanded, scratch)
        if "V" in only:
            testV(arguments.normal, arguments.sanitized, arguments.commanded, scratch)

    print(f"\n{len(failed)} failed" if failed else "\nall passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
