# The status document: what `workers status --json` prints and the dashboard reads

**Status: a proposal by the reviewer (2026-11-14), version 1, with the optional fields added on the same day after the dashboard's plan (marked "added").** The dashboard is prototyped against it; the design worker's `workers status --json` is to produce it. A change to this file goes through the reviewer, so that the two do not drift apart.

Rules:
- One JSON object, UTF-8. Unknown fields are ignored by a reader; a missing optional field means "not known".
- **Every value that is not measured by the system says where it comes from** (`source`): `measured` (the system's accounting), `recorded` (the broker's record), `derived` (computed by the tools), `self-reported` (asked inside the worker's own view), `claimed` (the agent's own words). A reader shows `claimed` values apart from the others and never as a fact.
- Sizes are bytes, times are seconds since 1970 (UTC), durations are seconds, shares are numbers from 0 to 1.
- Text written by an agent (`claimed` and `self-reported` strings, to-do items, commands) may contain anything. The producer cuts each to 4096 bytes; a reader must still treat it as untrusted.
- Added after the dashboard's report: a value that is not known is **left out**, never written as `null`.
- Added: project, branch and name together are unique among `workers`.
- Added: at most 2000 workers, and at most 20 entries each in `jobs`, `reviews.verdicts` and `memoryStops.last`; `memoryStops.last` and `runs` are newest first.
- Added: if the document is written to a file, it is written to a new file and renamed into place, so that a reader never sees half of it.
- Added: the producer writes valid UTF-8 and no unpaired surrogate escapes (such as `\udc80`), replacing what is not valid in an agent's text, so that one agent's text cannot make the whole document unreadable. A reader that meets an unreadable document keeps showing the last good one and says so.

```json
{
  "version": 1,
  "generated": 1794650000,
  "machine": {
    "memory": { "used": 9100000000, "limit": 19327352832, "peak": 12000000000 },
    "agentsMemory": { "used": 1200000000, "limit": 6442450944, "peak": 2100000000 },
    "agentsCpu": { "share": 1.7, "limit": 4.0 },
    "memoryStops": { "count": 2, "last": [ { "time": 1794640000, "worker": "alpha/solver/w1", "what": "job" } ] },
    "cpus": { "count": 28, "timing": "0-3", "timingReserved": false },
    "queue": {
      "slots": { "taken": 2, "total": 5 },
      "parallel": { "taken": 0, "total": 1 },
      "timing": { "taken": 0, "total": 1 },
      "exclusive": false,
      "waiting": 1
    },
    "disk": {
      "workers": { "used": 31000000000, "limit": 214748364800 },
      "scratch": { "used": 120000000000, "limit": 644245094400 }
    }
  },
  "workers": [
    {
      "project": "alpha",
      "branch": "solver",
      "name": "w1",
      "role": "implementer",
      "state": { "value": "implementing", "source": "derived" },
      "running": { "value": true, "since": 1794646000 },
      "lastRun": 1794646000,
      "memory": { "used": 410000000, "limit": 3221225472, "peak": 900000000 },
      "cpu": { "share": 0.4, "seconds": 812 },
      "gpuMemory": { "used": 0 },
      "folder": { "used": 300000000, "limit": 10737418240 },
      "scratch": { "used": 4200000000, "limit": 53687091200 },
      "jobs": [
        { "mode": "run", "since": 1794649000, "state": "running", "memory": { "used": 5200000000, "peak": 6100000000 }, "cpu": { "share": 7.6 }, "command": "pytest tests/solver" }
      ],
      "steps": {
        "done": 3, "total": 7, "current": "Add the boundary term to the residual", "changed": 1794648500, "source": "claimed",
        "items": [
          { "text": "Read the residual assembly", "state": "done" },
          { "text": "Add the boundary term to the residual", "state": "in work" },
          { "text": "Extend the test of the residual", "state": "open" }
        ]
      },
      "intent": { "approved": true, "approach": 2, "approvedAt": 1794640000, "changedSinceApproval": false, "source": "recorded" },
      "lastQueuedRun": { "mode": "run", "time": 1794648000, "exit": 0, "duration": 95, "onCurrentCommit": true, "source": "recorded" },
      "runs": [ { "mode": "run", "time": 1794648000, "exit": 0, "duration": 95, "onCurrentCommit": true, "command": "pytest tests/solver" } ],
      "acceptance": { "value": "passed", "onCurrentCommit": true, "time": 1794648000, "source": "recorded" },
      "commits": { "ahead": 4, "behind": 0, "uncommitted": { "value": true, "source": "self-reported" }, "source": "derived" },
      "reviews": { "count": 1, "outdated": 0, "verdicts": [ { "by": "r1", "value": "needs changes", "source": "claimed" } ], "source": "derived" },
      "claim": { "value": "Residual assembled; boundary term next", "source": "claimed" },
      "removable": { "value": false, "source": "derived" }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `machine.memory`, `machine.agentsMemory` | All workers together, and all agents together, against their limits; `peak` is the highest value since the last restart |
| `machine.agentsCpu` | Added. The processor share of all agents together against their shared limit, in processors. A single agent or job has no processor limit of its own, so `workers[].cpu` and `jobs[].cpu` have none |
| `machine.memoryStops` | How often a process was stopped for memory, and the last few |
| `machine.queue` | Slots and tokens taken; whether an exclusive job holds the machine; requests waiting |
| `workers[].role` | `implementer`, `reviewer`, `deep-reviewer`, `manager`, or `plain` for an ordinary pi session |
| `workers[].state.value` | `planned`, `approved`, `implementing`, `ready for review`, `reviewed`, `merged`, `removable`, or `idle` for a role without these stages |
| `workers[].running` | Whether its sandbox runs, and since when; `lastRun` is the start of the last one |
| `workers[].memory`, `cpu`, `gpuMemory` | The agent's own sandbox. `cpu.share` is in processors (1.0 is one busy processor) |
| `workers[].memoryStops` | Added, optional: `{ "count": 1 }`, how often this worker's agent or one of its jobs was stopped for memory since the last restart |
| `workers[].jobs[]` | Its queued jobs: `state` is `running` or `waiting`; `command` is the agent's text. Added: `memory.peak`. A job has no memory limit of its own; it counts against `machine.memory` |
| `workers[].steps` | From the agent's own to-do list: how many done of how many, the item in work, when the list last changed. Added, optional: `items`, the whole list in order, each with its `state` (`done`, `in work`, `open`); at most 100 items |
| `workers[].intent` | Whether the user approved the intent, which approach, and whether the form changed afterwards |
| `workers[].runs` | Added, optional: the last queued runs, newest first, at most 20; `source` is `recorded` for all, `command` is the agent's text |
| `workers[].lastQueuedRun`, `acceptance` | The broker's records. `acceptance.value` is `passed`, `failed`, `stale` (passed on an older commit) or `never run` |
| `workers[].commits` | Against its branch in the project |
| `workers[].reviews` | Reviews that ran against it; `outdated` counts those of an older commit |
| `workers[].claim` | One line in the agent's own words |
