#!/usr/bin/env python3
"""Regression tests for round 4 of the workers' live overview."""

import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time


ENVIRONMENT = dict(os.environ, TERM="xterm-256color", NO_COLOR="1")


def check(condition, message, detail=""):
    if condition:
        print(f"ok   {message}")
        return True
    print(f"FAIL {message}" + (f": {detail}" if detail else ""))
    return False


def machine():
    return {
        "memory": {},
        "agentsMemory": {},
        "agentsCpu": {},
        "memoryStops": {"count": 0, "last": []},
        "cpus": {},
        "queue": {
            "slots": {},
            "parallel": {},
            "timing": {},
            "exclusive": False,
            "waiting": 0,
        },
    }


def worker(project, branch, name, role, **extra):
    value = {
        "project": project,
        "branch": branch,
        "name": name,
        "role": role,
        "state": {"value": "idle", "source": "derived"},
        "running": {"value": False},
    }
    value.update(extra)
    return value


def run_frame(binary, document, detail=None, width=180, height=60):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        json.dump(document, file)
        path = file.name
    try:
        command = [binary, "--once", "--file", path, "--width", str(width), "--height", str(height)]
        if detail is not None:
            command += ["--detail", str(detail)]
        return subprocess.run(command, capture_output=True, text=True, env=ENVIRONMENT, timeout=30)
    finally:
        os.unlink(path)


def dashboard_document():
    places = {
        "copy": "/given/copies/alpha/a/i1",
        "reports": "/given/reports/alpha/a/i1",
        "records": "/given/records/alpha/a/i1",
        "task": "/given/tasks/alpha/a/i1.md",
        "scratch": "/given/scratch/alpha/a/i1",
    }
    return {
        "version": 1,
        "generated": 1794650000,
        "machine": machine(),
        "workers": [
            worker("beta", "z", "iz", "implementer"),
            worker("alpha", "a", "r1", "reviewer",
                   review={"implementers": ["i1", "i2"], "removableWithMerged": False, "source": "derived"}),
            worker("ordinary-b", "plain", "202", "plain",
                   places={"records": "/given/plain/records.jsonl", "scratch": "/given/plain/scratch"}),
            worker("alpha", "b", "ib", "implementer"),
            worker("alpha", "manager", "mb", "manager",
                   removal={"value": "removed by its own command", "source": "derived"}),
            worker("alpha", "manager", "ma", "manager",
                   removal={"value": "removed by its own command", "source": "derived"}),
            worker("alpha", "a", "d1", "deep-reviewer",
                   removal={"value": "removed by its own command", "source": "derived"}),
            worker("alpha", "a", "i2", "implementer"),
            worker("ordinary-a", "plain", "101", "plain"),
            worker("alpha", "a", "i1", "implementer", places=places,
                   nextStep={"command": "workers approve alpha/a/i1", "source": "derived"}),
        ],
    }


def test_dashboard(binary, commanded):
    passed = True
    document = dashboard_document()
    overview = run_frame(binary, document)
    passed &= check(overview.returncode == 0 and not overview.stderr,
                    "R4 dashboard fixture renders cleanly", overview.stderr[:300])
    frame = overview.stdout
    positions = {name: frame.find(name) for name in ("ma", "mb", "i1", "i2", "r1", "d1", "ib", "iz", "101", "202")}
    order = [positions[name] for name in ("ma", "mb", "i1", "i2", "r1", "d1", "ib", "iz", "101", "202")]
    passed &= check(all(position >= 0 for position in order) and order == sorted(order)
                    and len(re.findall(r"^    r1\s+reviewer\s", frame, re.MULTILINE)) == 1,
                    "R4 managers are ordered by name and a multi-implementer reviewer appears once under its branch",
                    repr(positions))
    passed &= check("Ordinary sessions" in frame and frame.count("PROJECT alpha") == 1
                    and "\n  a\n" in frame and "\n  b\n" in frame,
                    "R4 the overview labels one ordinary-session block and keeps alpha's branches in one project block")

    implementer = run_frame(binary, document, detail=2).stdout
    passed &= check(all(path in implementer for path in document["workers"][9]["places"].values()),
                    "R4 an implementer's detail shows every path supplied by the document")
    passed &= check("workers approve alpha/a/i1" in implementer,
                    "R4 a derived next command is shown in the detail")

    reviewer = run_frame(binary, document, detail=4).stdout
    passed &= check("i1, i2" in reviewer and "workers remove --merged" in reviewer and "not now" in reviewer,
                    "R4 a reviewer names every implementer it follows and whether remove --merged takes it")

    manager = run_frame(binary, document, detail=0).stdout
    deep = run_frame(binary, document, detail=5).stdout
    passed &= check("removed by its own command" in manager and "removed by its own command" in deep,
                    "R4 managers and deep reviewers say that their own command removes them")

    plain = run_frame(binary, document, detail=9).stdout
    passed &= check("Answer the user" not in plain and "pytest ordinary" not in plain,
                    "R4 an ordinary session does not show project-shared to-do items or runs as its own")
    passed &= check("an ordinary session has none" in plain and "an ordinary session has no folder" in plain,
                    "R4 worker-only facts and the missing worker folder are stated in words for an ordinary session")
    passed &= check("/given/plain/records.jsonl" in plain and "/given/plain/scratch" in plain,
                    "R4 an ordinary session shows the supplied records and scratch paths")

    old = json.loads(json.dumps(document))
    for entry in old["workers"]:
        for field in ("places", "nextStep", "review", "removal"):
            entry.pop(field, None)
    old_frame = run_frame(binary, old)
    passed &= check(old_frame.returncode == 0 and "alpha" in old_frame.stdout,
                    "R4 a document from an older producer still renders")

    slow_environment = dict(ENVIRONMENT, WORKERS_WATCH_TEST_SLOW="1")
    begun = time.monotonic()
    slow = subprocess.run([commanded, "--once", "--width", "160", "--height", "50"],
                          capture_output=True, text=True, env=slow_environment, timeout=20)
    elapsed = time.monotonic() - begun
    passed &= check(slow.returncode == 0 and 9.5 <= elapsed < 15
                    and "counting a large project's history" in slow.stdout
                    and "producer may have stopped" not in slow.stdout,
                    "R4 a slow status call is described as counting a large project's history",
                    f"{elapsed:.1f}s; {slow.stdout[:400]!r}")
    return passed


def git(command, cwd, git_program, environment=None):
    subprocess.run([git_program, *command], cwd=cwd, env=environment, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_fake_approve(path):
    path.write_text(
        """class Refused(Exception):\n    pass\n\nclass Worker:\n    def __init__(self, config, full):\n        self.full = full\n    def reference(self):\n        project, branch, name = self.full.split('/')\n        return f'refs/heads/worker/{branch}/{name}'\n    def approval(self):\n        return None\n\ndef state(worker):\n    return 'no approval'\n""",
        encoding="utf-8",
    )


# The remembered-start helper that status.py loads; set from --start-spec in main()
START_SPEC = None


def status_config(root, approve, git_program):
    return {
        "startSpec": START_SPEC,
        "approve": str(approve),
        "approveConfig": {},
        "git": str(git_program),
        "findmnt": "/bin/false",
        "helper": [],
        "locks": str(root / "locks"),
        "timingCpus": "",
    }


def load_status(status_path, environment):
    old = {key: os.environ.get(key) for key in ("HOME", "XDG_RUNTIME_DIR")}
    os.environ.update(environment)
    try:
        specification = importlib.util.spec_from_file_location("round4_status", status_path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_plain_status(status_path, git_program):
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        home = root / "home"
        runtime = root / "runtime"
        home.mkdir()
        runtime.mkdir()
        approve = root / "approve.py"
        write_fake_approve(approve)
        environment = {"HOME": str(home), "XDG_RUNTIME_DIR": str(runtime)}
        module = load_status(status_path, environment)
        os.environ.update(environment)
        try:
            status = module.Status(status_config(root, approve, git_program))
            key = "demo-abc123"
            scope = f"pi-{key}-4321.scope"
            groups = root / "groups"
            (groups / "workers-agents.slice" / scope).mkdir(parents=True)
            status.groups = str(groups)

            sessions = home / ".pi/agent/sessions/demo-abc123fedcba/--session--"
            sessions.mkdir(parents=True)
            sample = pathlib.Path(status_path).with_name("sample-session.jsonl")
            shutil.copyfile(sample, sessions / "session.jsonl")

            records = home / f".local/state/workers-plain/{key}"
            records.mkdir(parents=True)
            (records / "records.jsonl").write_text(
                '{"id":"20261116T080000-1","state":"started","mode":"run","command":["pytest","plain"]}\n'
                '{"id":"20261116T080000-1","exit":0,"duration_s":4,"mode":"run","command":["pytest","plain"]}\n',
                encoding="utf-8",
            )
            found = status._sessions({}, set())

            worker_state = home / ".local/state/workers/project"
            (worker_state / "roles/branch").mkdir(parents=True)
            (worker_state / "roles/branch/implementer").write_text("implementer\n", encoding="utf-8")
            (worker_state / "roles/branch/reviewer").write_text("reviewer\n", encoding="utf-8")
            (worker_state / "roles/manager").mkdir(parents=True)
            (worker_state / "roles/manager/manager").write_text("manager\n", encoding="utf-8")
            (worker_state / "reviews/branch/implementer").mkdir(parents=True)
            (worker_state / "reviews/branch/implementer/reviewer").write_text("commit\n", encoding="utf-8")
            reviewer = status._worker("project", "branch", "reviewer", {}, [], {})
            manager = status._worker("project", "manager", "manager", {}, [], {})
        finally:
            for key_, value in environment.items():
                if os.environ.get(key_) == value:
                    os.environ.pop(key_)
        plain_ok = check(len(found) == 1 and "steps" not in found[0] and "runs" not in found[0]
                         and "lastQueuedRun" not in found[0]
                         and found[0].get("places", {}).get("records") == str(records / "records.jsonl")
                         and found[0].get("places", {}).get("scratch", "").endswith(f"/{key}/plain/session"),
                         "R4 status omits project-shared ordinary-session to-dos and runs, but keeps assignable paths",
                         repr(found))
        relation_ok = check(reviewer.get("review") == {
                                "implementers": ["implementer"],
                                "removableWithMerged": False,
                                "source": "derived",
                            }
                            and manager.get("removal") == {
                                "value": "removed by its own command",
                                "source": "derived",
                            },
                            "R4 status derives reviewer relationships and own-command removal",
                            repr((reviewer, manager)))
        return plain_ok and relation_ok


def make_large_history(root, git_program):
    project = root / "project"
    project.mkdir()
    git(["init", "-q", "-b", "main"], project, git_program)
    environment = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                       GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
    (project / "data").write_bytes(b"start\n")
    git(["add", "data"], project, git_program, environment)
    git(["commit", "-q", "-m", "start"], project, git_program, environment)
    git(["switch", "-q", "-c", "big"], project, git_program, environment)
    for number in range(60):
        with (project / "data").open("ab") as file:
            file.write(os.urandom(64 * 1024))
        git(["add", "data"], project, git_program, environment)
        git(["commit", "-q", "-m", f"history {number}"], project, git_program, environment)
        git(["branch", f"old-{number}"], project, git_program, environment)
    return project, environment


def test_first_status(status_path, git_program):
    passed = True
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        home = root / "home"
        runtime = root / "runtime"
        home.mkdir()
        runtime.mkdir()
        project, git_environment = make_large_history(root, git_program)
        copy = home / "workers/large/big/w1/repo"
        copy.parent.mkdir(parents=True)
        git(["clone", "-q", str(project), str(copy)], root, git_program, git_environment)
        git(["switch", "-q", "-c", "worker/big/w1", "big"], copy, git_program, git_environment)
        (copy / "worker-change").write_text("worker\n", encoding="utf-8")
        git(["add", "worker-change"], copy, git_program, git_environment)
        git(["commit", "-q", "-m", "worker"], copy, git_program, git_environment)

        state = home / ".local/state/workers/large"
        (state / "roles/big").mkdir(parents=True)
        (state / "roles/big/w1").write_text("implementer\n", encoding="utf-8")
        (state / "main").write_text(str(project) + "\n", encoding="utf-8")
        approve = root / "approve.py"
        write_fake_approve(approve)
        wrapper = root / "slow-git"
        wrapper.write_text(
            "#!/bin/sh\nfor word in \"$@\"; do if [ \"$word\" = fetch ]; then sleep 5.5; break; fi; done\n"
            f"exec {git_program} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        config = root / "config.json"
        config.write_text(json.dumps(status_config(root, approve, wrapper)), encoding="utf-8")
        environment = dict(os.environ, HOME=str(home), XDG_RUNTIME_DIR=str(runtime))
        command = [sys.executable, str(status_path), "--config", str(config), "--json"]

        begun = time.monotonic()
        first = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=35)
        elapsed = time.monotonic() - begun
        first_document = json.loads(first.stdout) if first.returncode == 0 and first.stdout else {}
        commits = first_document.get("workers", [{}])[0].get("commits", {}) if first_document.get("workers") else {}
        passed &= check(first.returncode == 0 and elapsed < 8 and commits.get("pending") is True
                        and "ahead" not in commits and "behind" not in commits,
                        "R4 the first status of generated large history answers inside the overview limit with counts not known yet",
                        f"{elapsed:.1f}s; {commits!r}; {first.stderr[:300]!r}")

        notes = runtime / "workers/status-notes.json"
        deadline = time.monotonic() + 25
        counted = False
        while time.monotonic() < deadline:
            try:
                remembered = json.loads(notes.read_text(encoding="utf-8"))
                counted = "ahead" in remembered.get("commits", {}).get("large", {}).get("workers", {}).get("big/w1", {})
            except (OSError, ValueError):
                counted = False
            if counted:
                break
            time.sleep(0.25)
        second = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=8)
        second_document = json.loads(second.stdout) if second.returncode == 0 and second.stdout else {}
        second_commits = second_document.get("workers", [{}])[0].get("commits", {}) if second_document.get("workers") else {}
        passed &= check(counted and second.returncode == 0 and second_commits.get("ahead") == 1
                        and second_commits.get("pending") is not True,
                        "R4 deferred commit counts replace not-known with the measured result",
                        repr(second_commits))
        worker_value = second_document.get("workers", [{}])[0] if second_document.get("workers") else {}
        passed &= check(worker_value.get("places", {}).get("copy") == str(copy)
                        and worker_value.get("nextStep", {}).get("command") == "workers approve large/big/w1"
                        and worker_value.get("nextStep", {}).get("source") == "derived",
                        "R4 status composes worker paths and approval commands itself",
                        repr(worker_value))
    return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal", required=True)
    parser.add_argument("--commanded", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--sample-session", required=True)
    parser.add_argument("--git", required=True)
    parser.add_argument("--start-spec", required=True)
    arguments = parser.parse_args()
    global START_SPEC
    START_SPEC = arguments.start_spec

    # Put the approved sample beside the imported status module without reading a real session
    status_copy_root = tempfile.TemporaryDirectory()
    try:
        copied_status = pathlib.Path(status_copy_root.name) / "status.py"
        copied_sample = pathlib.Path(status_copy_root.name) / "sample-session.jsonl"
        shutil.copyfile(arguments.status, copied_status)
        shutil.copyfile(arguments.sample_session, copied_sample)
        passed = test_dashboard(arguments.normal, arguments.commanded)
        passed &= test_plain_status(copied_status, arguments.git)
        passed &= test_first_status(copied_status, arguments.git)
    finally:
        status_copy_root.cleanup()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
