#!/usr/bin/env python3
"""Regression tests for round 5 of the workers' live overview."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import run  # noqa: E402


ENVIRONMENT = dict(os.environ, TERM="xterm-256color", NO_COLOR="1")
LONG_TASK = "Compare the acceptance evidence with the independent reference and prepare the reviewer handoff"


def check(condition, message, detail=""):
    if condition:
        print(f"ok   {message}")
        return True
    print(f"FAIL {message}" + (f": {detail}" if detail else ""))
    return False


def machine(high=False):
    gib = 1024**3
    return {
        "memory": {"used": (17 if high else 4) * gib, "peak": (17.2 if high else 5) * gib, "limit": 18 * gib},
        "agentsMemory": {"used": 1 * gib, "peak": 1.2 * gib, "limit": 6 * gib},
        "agentsCpu": {"share": 0.5, "limit": 4},
        "memoryStops": {"count": 0, "last": []},
        "cpus": {"count": 16, "timing": "0-1", "timingReserved": True},
        "queue": {
            "slots": {"taken": 0, "total": 5},
            "parallel": {"taken": 0, "total": 1},
            "timing": {"taken": 0, "total": 1},
            "exclusive": False,
            "waiting": 0,
        },
        "disk": {
            "workers": {"used": 2 * gib, "limit": 200 * gib},
            "scratch": {"used": 3 * gib, "limit": 600 * gib},
        },
    }


def worker(project, branch, name, role, state="idle", task=None, done=None, total=None, acceptance=None, high=False):
    gib = 1024**3
    value = {
        "project": project,
        "branch": branch,
        "name": name,
        "role": role,
        "state": {"value": state, "source": "derived"},
        "running": {"value": False},
        "memory": {"used": (2.8 if high else 0.2) * gib, "peak": (2.9 if high else 0.3) * gib, "limit": 3 * gib},
        "cpu": {"share": 0},
        "folder": {"used": 0.2 * gib, "limit": 10 * gib},
        "scratch": {"used": 0.4 * gib, "limit": 50 * gib},
    }
    if done is not None:
        value["steps"] = {
            "done": done,
            "total": total,
            "changed": 1794649000,
            "source": "claimed",
        }
        if task:
            value["steps"]["current"] = task
    if acceptance:
        value["acceptance"] = {"value": acceptance, "source": "recorded"}
    return value


def layoutDocument():
    workers = [
        worker("alpha", "manager", "coordination", "manager"),
        worker("alpha", "boundary-l3", "packet-review", "implementer", "implementing", LONG_TASK, 3, 8),
        worker("alpha", "boundary-l3", "packet-review-r1", "reviewer"),
        worker("alpha", "boundary-l3", "edge-audit", "deep-reviewer"),
        worker("alpha", "retire-pyfoamfile", "retire", "implementer"),
        worker("alpha", "retire-pyfoamfile", "retire-r1", "reviewer"),
        worker("beta", "manager", "orchestration", "manager"),
        worker("beta", "benchmarking", "benchmark-runner", "implementer"),
        worker("beta", "benchmarking", "benchmark-review", "reviewer"),
        worker("beta", "context-guard", "context-guard", "implementer"),
        worker("beta", "context-guard", "context-review", "deep-reviewer"),
    ]
    roles = ("implementer", "reviewer", "deep-reviewer")
    branches = (("alpha", "boundary-l3"), ("alpha", "retire-pyfoamfile"),
                ("beta", "benchmarking"), ("beta", "context-guard"))
    for index in range(len(workers), 40):
        project, branch = branches[index % len(branches)]
        workers.append(worker(project, branch, f"worker-{index:02d}-audit", roles[index % len(roles)]))
    return {"version": 1, "generated": 1794650000, "machine": machine(), "workers": workers}


def paletteDocument():
    workers = [
        worker("alpha", "done", "completed-worker", "implementer", "reviewed", None, 8, 8, "passed"),
        worker("alpha", "trouble", "trouble-worker", "implementer", "implementing", "Repair the failing test", 2, 5,
               "failed", True),
    ]
    return {"version": 1, "generated": 1794650000, "machine": machine(True), "workers": workers}


def frame(binary, document, width=190, height=90):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        json.dump(document, file)
        path = file.name
    try:
        return subprocess.run(
            [binary, "--once", "--file", path, "--width", str(width), "--height", str(height)],
            capture_output=True,
            text=True,
            env=ENVIRONMENT,
            timeout=30,
        )
    finally:
        os.unlink(path)


def precedingBlanks(lines, index):
    count = 0
    for line in reversed(lines[:index]):
        if line:
            break
        count += 1
    return count


def testLayout(binary):
    passed = True
    result = frame(binary, layoutDocument())
    passed &= check(result.returncode == 0 and not result.stderr, "R5 the 40-worker frame renders cleanly", result.stderr[:300])
    lines = result.stdout.splitlines()

    alpha = lines.index("PROJECT alpha") if "PROJECT alpha" in lines else -1
    beta = lines.index("PROJECT beta") if "PROJECT beta" in lines else -1
    boundary = lines.index("  boundary-l3") if "  boundary-l3" in lines else -1
    retire = lines.index("  retire-pyfoamfile") if "  retire-pyfoamfile" in lines else -1
    passed &= check(alpha >= 0 and beta > alpha and boundary > alpha and retire > boundary
                    and "alpha / boundary-l3" not in result.stdout,
                    "R5 project and branch headings use soft hierarchy without repeating the project")

    manager = next((line for line in lines if "coordination" in line), "")
    implementer = next((line for line in lines if "packet-review" in line and "packet-review-r1" not in line), "")
    deep = next((line for line in lines if "edge-audit" in line), "")
    passed &= check(re.match(r"^[> ] coordination\s+manager\s", manager) is not None
                    and re.match(r"^[> ]   packet-review\s+implementer\s", implementer) is not None,
                    "R5 managers are indented two spaces and branch workers four spaces",
                    repr((manager, implementer)))
    roleColumns = [manager.find("manager"), implementer.find("implementer"), deep.find("deep-reviewer")]
    passed &= check(min(roleColumns) >= 0 and len(set(roleColumns)) == 1,
                    "R5 full role names line up in one role column", repr(roleColumns))
    passed &= check("packet-review" in implementer and "…" not in implementer[:roleColumns[1]],
                    "R5 worker names receive their needed room before optional columns", implementer)

    passed &= check(boundary >= 0 and retire >= 0 and beta >= 0
                    and precedingBlanks(lines, boundary) == 1
                    and precedingBlanks(lines, retire) == 1
                    and precedingBlanks(lines, beta) == 2,
                    "R5 one blank line separates branches and two separate projects",
                    repr((precedingBlanks(lines, boundary) if boundary >= 0 else None,
                          precedingBlanks(lines, retire) if retire >= 0 else None,
                          precedingBlanks(lines, beta) if beta >= 0 else None)))

    heads = next((line for line in lines if "IN WORK" in line and "CHANGED" in line), "")
    todoStart = heads.find("IN WORK")
    todoEnd = heads.find("CHANGED")
    workerIndex = next((index for index, line in enumerate(lines) if "packet-review" in line and "packet-review-r1" not in line), -1)
    wrapped = []
    if todoStart >= 0 and todoEnd > todoStart and workerIndex >= 0:
        for line in lines[workerIndex:workerIndex + 2]:
            wrapped.append(line[todoStart:todoEnd].strip())
    passed &= check(" ".join(part for part in wrapped if part) == "~" + LONG_TASK and len(wrapped) == 2,
                    "R5 IN WORK wraps onto at most one continuation line without losing the task", repr(wrapped))
    return passed


def testPalette(binary):
    passed = True
    document = paletteDocument()
    result = frame(binary, document, width=170, height=40)
    text = result.stdout
    low = next((line for line in text.splitlines() if "completed-worker" in line), "")
    high = next((line for line in text.splitlines() if "trouble-worker" in line), "")
    passed &= check("··" not in text and "█" not in low and "▒" not in low and "█" in high,
                    "R5 low resource values are plain figures and meters appear only near a limit",
                    repr((low, high)))

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        json.dump(document, file)
        path = file.name
    terminal = run.Terminal([binary, "--file", path], 170, 40)
    try:
        started = terminal.waitFor("IN WORK", 20) is not None
        terminal.read(0.5)
        completed = run.styleAt(terminal.output, "8/8")
        reviewed = run.styleAt(terminal.output, "reviewed")
        success = run.styleAt(terminal.output, "passed")
        failure = run.styleAt(terminal.output, "failed")
        colours = run.coloursIn(terminal.output)
        mark = terminal.send("?")
        helpShown = terminal.waitFor("red means trouble", 5, mark) is not None
        helpText = terminal.plain(mark)
        status = terminal.close()
    finally:
        if terminal.process.poll() is None:
            terminal.close()
        os.unlink(path)
    passed &= check(started and status == 0 and completed is not None and "colour" not in completed
                    and reviewed is not None and "colour" not in reviewed
                    and success is not None and "colour" not in success
                    and failure is not None and "colour" in failure
                    and colours <= {31, 33},
                    "R5 colour is reserved for warning and trouble, not progress, state or success",
                    repr((completed, reviewed, success, failure, sorted(colours))))
    passed &= check(helpShown and "yellow means warning" in helpText and "needs you" in helpText,
                    "R5 the key explains each colour and reserves a needs-you state without inventing one",
                    helpText[-1000:])
    return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal", required=True)
    arguments = parser.parse_args()
    binary = os.path.abspath(arguments.normal)
    passed = testLayout(binary)
    passed &= testPalette(binary)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
