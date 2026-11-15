#!/usr/bin/env python3
"""Writes sample status documents (SCHEMA.md, version 1) that change over time, to watch workers-watch work.

  generate.py --stdout                      print one document and end
  generate.py --out PATH [--interval 2]     write a new document to PATH every few seconds, until interrupted

Every name in it is invented. The same seed gives the same documents.
"""

import argparse
import json
import os
import random
import sys
import time

GIB = 1024**3
MIB = 1024**2

# The limits of the invented machine
AGENT_MEMORY = 3 * GIB
AGENTS_MEMORY = 6 * GIB
WORKERS_MEMORY = 18 * GIB
AGENTS_CPU = 4.0
FOLDER = 10 * GIB
SCRATCH = 50 * GIB
SLOTS = 5

STAGES = ["planned", "approved", "implementing", "ready for review", "reviewed", "merged", "removable"]
TASKS = [
    "Read the residual assembly",
    "Write the test that fails",
    "Add the boundary term to the residual",
    "Extend the test of the residual",
    "Run the tests of the solver",
    "Update the documentation of the solver",
    "Record the validation run",
    "Compare the result with the reference",
    "Remove the duplicated helper",
]
REVIEW_TASKS = [
    "Read the diff against the branch",
    "Rerun the reproduction test",
    "Check the edge cases of the change",
    "Write the findings",
]
COMMANDS = ["pytest tests/solver", "ctest -R mesh", "make check", "pytest tests/io -k roundtrip"]
VERDICTS = ["needs changes", "ready", "blocked by missing evidence"]

# Project, branch, name, role, state: three projects, every role and every state
CAST = [
    ("alpha", "solver", "w1", "implementer", "implementing"),
    ("alpha", "solver", "w2", "implementer", "ready for review"),
    ("alpha", "solver", "r1", "reviewer", "idle"),
    ("alpha", "mesh", "w1", "implementer", "planned"),
    ("alpha", "mesh", "w2", "implementer", "approved"),
    ("alpha", "mesh", "d1", "deep-reviewer", "idle"),
    ("beta", "main", "m1", "manager", "idle"),
    ("beta", "main", "w1", "implementer", "reviewed"),
    ("beta", "main", "w2", "implementer", "merged"),
    ("beta", "io", "w1", "implementer", "removable"),
    ("gamma", "docs", "w1", "implementer", "implementing"),
    ("gamma", "docs", "p1", "plain", "idle"),
]
BRANCHES = [("alpha", "solver"), ("alpha", "mesh"), ("beta", "main"), ("beta", "io"), ("gamma", "docs")]
ROLES = ["implementer", "implementer", "implementer", "reviewer", "deep-reviewer", "manager", "plain"]


def stepsOf(rng, role, state, now):
    """The to-do list an agent would report for its role and state."""
    tasks = TASKS if role == "implementer" else REVIEW_TASKS
    total = rng.randint(4, len(tasks))
    stage = STAGES.index(state) if state in STAGES else None
    if role in ("manager", "plain") or stage == 0:
        return None
    if stage is None:
        done = rng.randint(0, total - 1)
    elif stage == 1:
        done = 0
    elif stage == 2:
        done = rng.randint(1, total - 1)
    else:
        done = total
    steps = {"done": done, "total": total, "changed": now - rng.randint(60, 9000), "source": "claimed", "items": []}
    for index in range(total):
        itemState = "done" if index < done else ("in work" if index == done else "open")
        steps["items"].append({"text": tasks[index], "state": itemState})
    if done < total:
        steps["current"] = tasks[done]
    return steps


def newWorker(rng, project, branch, name, role, state, now):
    """One worker in a given state, with everything that follows from the state."""
    stage = STAGES.index(state) if state in STAGES else None
    running = (state in ("implementing", "idle")) or (stage is not None and rng.random() < 0.2)
    used = rng.randint(150, 900) * MIB if running else 0
    worker = {
        "project": project,
        "branch": branch,
        "name": name,
        "role": role,
        "state": {"value": state, "source": "derived"},
        "running": {"value": running},
        "lastRun": now - rng.randint(600, 90000),
        "memory": {"used": used, "limit": AGENT_MEMORY, "peak": max(used, rng.randint(300, 2000) * MIB)},
        "cpu": {"share": round(rng.uniform(0.0, 0.6), 1) if running else 0.0, "seconds": rng.randint(10, 5000)},
        "gpuMemory": {"used": 0},
        "folder": {"used": rng.randint(20, 900) * MIB, "limit": FOLDER},
        "scratch": {"used": rng.randint(0, 20000) * MIB, "limit": SCRATCH},
        "jobs": [],
        "runs": [],
        "removable": {"value": state == "removable", "source": "derived"},
    }
    if running:
        worker["running"]["since"] = worker["lastRun"]
    steps = stepsOf(rng, role, state, now)
    if steps:
        worker["steps"] = steps
        worker["claim"] = {"value": "Working on: " + steps.get("current", "everything is done"), "source": "claimed"}
    if role != "implementer":
        return worker

    # What only an implementer has: the approved intent, the tests, the commits and the reviews
    approved = stage >= 1
    worker["commits"] = {"ahead": 0, "behind": 0, "uncommitted": {"value": False, "source": "self-reported"}, "source": "derived"}
    worker["reviews"] = {"count": 0, "outdated": 0, "verdicts": [], "source": "derived"}
    worker["intent"] = {"approved": approved, "source": "recorded"}
    if approved:
        worker["intent"].update(approach=rng.randint(1, 3), approvedAt=now - rng.randint(4000, 90000), changedSinceApproval=False)
    worker["acceptance"] = {"value": "never run", "source": "recorded"}
    if stage >= 2:
        worker["commits"].update(ahead=rng.randint(1, 9), behind=rng.randint(0, 2))
        worker["commits"]["uncommitted"]["value"] = stage == 2
    if stage >= 3:
        finishRun(rng, worker, rng.choice(COMMANDS), now - rng.randint(300, 4000), 0)
    if stage >= 4:
        worker["reviews"].update(count=2, outdated=1)
        worker["reviews"]["verdicts"] = [
            {"by": "r1", "value": VERDICTS[0], "source": "claimed"},
            {"by": "d1", "value": VERDICTS[1], "source": "claimed"},
        ]
    if stage >= 5:
        worker["commits"].update(ahead=0, behind=0)
    return worker


def finishRun(rng, worker, command, when, status):
    """Records a queued run that ended, as the broker would."""
    run = {"mode": "run", "time": when, "exit": status, "duration": rng.randint(5, 900), "onCurrentCommit": True}
    worker["runs"] = ([dict(run, command=command)] + worker["runs"])[:20]
    worker["lastQueuedRun"] = dict(run, source="recorded")
    worker["acceptance"] = {
        "value": "passed" if status == 0 else "failed",
        "onCurrentCommit": True,
        "time": when,
        "source": "recorded",
    }


def newWorld(seed, count, now):
    rng = random.Random(seed)
    workers = [newWorker(rng, *entry, now) for entry in CAST[:count]]
    # Beyond the fixed cast: more workers of any role and state, spread over the branches
    for index in range(len(workers), count):
        project, branch = BRANCHES[index % len(BRANCHES)]
        role = rng.choice(ROLES)
        state = rng.choice(STAGES) if role == "implementer" else "idle"
        workers.append(newWorker(rng, project, branch, f"{role[0]}{index}", role, state, now))
    world = {"rng": rng, "now": now, "workers": workers, "stops": [], "stopCount": 0, "peak": 0, "agentsPeak": 0}
    # A fixed beginning, so that the first document already shows a job, an outdated review and two stops
    if workers:
        startJob(world, workers[0], now - 1000)
        workers[0]["jobs"][0]["state"] = "running"
    if len(workers) > 10:
        startJob(world, workers[10], now - 120)
    if len(workers) > 1:
        workers[1]["memory"]["peak"] = int(0.93 * AGENT_MEMORY)
        world["stops"] = [{"time": now - 10000, "worker": "alpha/solver/w1", "what": "job"}]
        world["stopCount"] = 2
        workers[0]["memoryStops"] = {"count": 2}
    return world


def startJob(world, worker, since):
    rng = world["rng"]
    used = rng.randint(200, 6000) * MIB
    worker["jobs"].append({
        "mode": "run",
        "since": since,
        "state": "waiting",
        "memory": {"used": used, "peak": used},
        "cpu": {"share": round(rng.uniform(0.5, 8.0), 1)},
        "command": rng.choice(COMMANDS),
    })


def advance(world, seconds):
    """Moves the invented machine on by some seconds: steps get done, jobs start and end, states change."""
    rng = world["rng"]
    world["now"] += seconds
    now = world["now"]
    for worker in world["workers"]:
        state = worker["state"]["value"]
        running = worker["running"]["value"]

        # Step 1. What a running agent uses moves a little; the peak follows
        if running:
            memory = worker["memory"]
            memory["used"] = int(min(0.97 * AGENT_MEMORY, max(100 * MIB, memory["used"] * rng.uniform(0.8, 1.2))))
            memory["peak"] = max(memory["peak"], memory["used"])
            worker["cpu"]["share"] = round(rng.uniform(0.0, 0.7), 1)
            worker["cpu"]["seconds"] += int(seconds * worker["cpu"]["share"])

        # Step 2. Its jobs: waiting ones start when a slot is free, running ones end and are recorded
        taken = sum(1 for other in world["workers"] for job in other["jobs"] if job["state"] == "running")
        for job in list(worker["jobs"]):
            if job["state"] == "waiting" and taken < SLOTS:
                job["state"] = "running"
                taken += 1
            elif job["state"] == "running":
                job["memory"]["used"] = int(min(9 * GIB, job["memory"]["used"] * rng.uniform(0.8, 1.3)))
                job["memory"]["peak"] = max(job["memory"]["peak"], job["memory"]["used"])
                if job["memory"]["used"] > 8 * GIB:
                    # The watcher stops a job that grows too far
                    worker["jobs"].remove(job)
                    world["stopCount"] += 1
                    worker["memoryStops"] = {"count": worker.get("memoryStops", {"count": 0})["count"] + 1}
                    name = f"{worker['project']}/{worker['branch']}/{worker['name']}"
                    world["stops"] = ([{"time": now, "worker": name, "what": "job"}] + world["stops"])[:5]
                elif rng.random() < 0.2:
                    worker["jobs"].remove(job)
                    finishRun(rng, worker, job["command"], now, 0 if rng.random() < 0.8 else 1)
        if state == "implementing" and not worker["jobs"] and rng.random() < 0.25:
            startJob(world, worker, now)

        # Step 3. The to-do list and the state move on
        steps = worker.get("steps")
        if steps and running and steps["done"] < steps["total"] and rng.random() < 0.3:
            steps["items"][steps["done"]]["state"] = "done"
            steps["done"] += 1
            steps["changed"] = now
            if steps["done"] < steps["total"]:
                steps["items"][steps["done"]]["state"] = "in work"
                steps["current"] = steps["items"][steps["done"]]["text"]
            else:
                steps.pop("current", None)
            worker["claim"] = {"value": "Working on: " + steps.get("current", "everything is done"), "source": "claimed"}
        if worker["role"] == "implementer":
            stage = STAGES.index(state)
            finished = stage != 2 or (steps and steps["done"] == steps["total"])
            if finished and not worker["jobs"] and rng.random() < 0.08:
                following = STAGES[(stage + 1) % len(STAGES)]
                fresh = newWorker(rng, worker["project"], worker["branch"], worker["name"], "implementer", following, now)
                fresh["memory"]["peak"] = max(fresh["memory"]["peak"], worker["memory"]["peak"])
                if "memoryStops" in worker:
                    fresh["memoryStops"] = worker["memoryStops"]
                worker.clear()
                worker.update(fresh)


def document(world):
    """The status document of the invented machine at this moment."""
    workers = world["workers"]
    jobs = [job for worker in workers for job in worker["jobs"]]
    # The limits hold on a real machine, so the sums never pass them here either
    agents = min(AGENTS_MEMORY, sum(worker["memory"]["used"] for worker in workers))
    used = min(WORKERS_MEMORY, agents + sum(job["memory"]["used"] for job in jobs if job["state"] == "running"))
    world["peak"] = max(world["peak"], used, int(1.3 * used) if not world["peak"] else 0)
    world["agentsPeak"] = max(world["agentsPeak"], agents, int(1.2 * agents) if not world["agentsPeak"] else 0)
    return {
        "version": 1,
        "generated": world["now"],
        "machine": {
            "memory": {"used": used, "limit": WORKERS_MEMORY, "peak": world["peak"]},
            "agentsMemory": {"used": agents, "limit": AGENTS_MEMORY, "peak": world["agentsPeak"]},
            "agentsCpu": {"share": round(min(AGENTS_CPU, sum(worker["cpu"]["share"] for worker in workers)), 1), "limit": AGENTS_CPU},
            "memoryStops": {"count": world["stopCount"], "last": world["stops"]},
            "cpus": {"count": 28, "timing": "0-3", "timingReserved": False},
            "queue": {
                "slots": {"taken": sum(1 for job in jobs if job["state"] == "running"), "total": SLOTS},
                "parallel": {"taken": 0, "total": 1},
                "timing": {"taken": 0, "total": 1},
                "exclusive": False,
                "waiting": sum(1 for job in jobs if job["state"] == "waiting"),
            },
            "disk": {
                "workers": {"used": min(200 * GIB, sum(worker["folder"]["used"] for worker in workers)), "limit": 200 * GIB},
                "scratch": {"used": min(600 * GIB, sum(worker["scratch"]["used"] for worker in workers)), "limit": 600 * GIB},
            },
        },
        "workers": workers,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=len(CAST), help="how many workers (default: the fixed cast of 12)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between two documents")
    parser.add_argument("--time", type=int, default=None, help="the time of the first document (default: now, or a fixed time with --stdout)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--stdout", action="store_true", help="print one document and end")
    target.add_argument("--out", help="the file to write again and again")
    arguments = parser.parse_args()

    if arguments.stdout:
        world = newWorld(arguments.seed, arguments.workers, arguments.time or 1794650000)
        json.dump(document(world), sys.stdout, indent=1)
        print()
        return
    world = newWorld(arguments.seed, arguments.workers, arguments.time or int(time.time()))
    try:
        while True:
            # As SCHEMA.md asks of a producer: a new file, renamed into place, so that no reader meets half a document
            with open(arguments.out + ".new", "w", encoding="utf-8") as file:
                json.dump(document(world), file)
            os.replace(arguments.out + ".new", arguments.out)
            time.sleep(arguments.interval)
            advance(world, int(time.time()) - world["now"])
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
