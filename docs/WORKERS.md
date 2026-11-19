# Several agents on one machine

`modules/dev/workers.nix` defines `nixos.workers`: what every pi sandbox ("worker") gets of the disk, and what keeps workers apart. The pi launcher (`modules/dev/pi.nix`) applies it. This page covers the layout, the job queue, the limits on memory and cores, the roles, what the launcher checks at a start, and the way work travels through git. **No agent writes your project:** every worker that changes code, the manager included, works in a copy of its own, and you bring the result into the project yourself. Everything here is set from outside the sandbox; an agent's instructions only say how to use it.

## Where a worker's things are

| Place | Contents | Storage |
| --- | --- | --- |
| `~/workers/<project>/<branch>/<name>/` | `repo/` (the worker's copy of the project), `reports/`, `records/`, `sessions/` (its pi sessions) | A dataset of its own with a limit (`hostSpec.workers.folderQuota`); snapshots and backup |
| `~/scratch/workers/<project>/<branch>/<name>/` | Raw output | A dataset of its own with a limit (`areaQuota`); no snapshots, no backup |
| `~/workers/<project>/instructions/` | The task files, written by the project's manager | A dataset with a limit (`instructionsQuota`) |
| `~/workers/<project>/archive/` | For what is kept of removed workers | A dataset |

`<project>` is the name of the folder `pi` is started in (the repository around it). Names are 1 to 48 letters, digits, `.`, `_` or `-`; `manager`, `archive`, `instructions`, `plain` and `old` cannot be branch names.

`~/workers` and `~/scratch/workers` and the levels down to a worker's own folder belong to root (`modules/storage/disk.nix` declares the two datasets). You cannot create or rename anything there as your ordinary user, and neither can a program running as you: that is what lets the helper below mount safely.

**A folder made by you with root access:** `~/workers/<project>/old/` is the one supported name for a user-made folder in a project's worker tree. The tools leave it alone: listing, status, starts on other branches and `remove --merged` do not change it. A start on branch `old` is refused before anything is created or mounted. Other hand-made folders there are unsupported; keep them outside the worker tree.

## Start a worker

```bash
cd ~/projects/<project>
pi --role manager                                                        # the project's manager
pi --branch boundary --name paired-conditions                            # an implementer
pi --role reviewer --branch boundary --name review-1 --of paired-conditions
pi --role deep-reviewer --branch boundary --name correctness
worker-shell --branch boundary --name me                                 # the same sandbox with a shell
```

The options come before pi's own. Who a worker is comes from this command line alone: the environment and the project's files are within an agent's reach. The first start creates the worker's folder and scratch area. An implementer's copy stays read-only until you approve its intent (below).

| Role | Reads and writes | Reads only | Starts in |
| --- | --- | --- | --- |
| `implementer` (default with `--branch`) | Its `repo/`, `reports/`, `sessions/`, its scratch area | The project's history (`.git`); each manager's copy (`repo/`); its `records/` | Its `repo/` |
| `reviewer` | Its `reports/`, `sessions/`, its scratch area | Its `repo/`: a clean copy with what the one implementer named with `--of` committed. That implementer's `records/`, `reports/` and scratch area; the project's history; its own `records/` | Its `reports/` |
| `deep-reviewer` | Its `reports/`, `sessions/`, its scratch area | The project. Its `repo/`: a clean copy with what the managers and the implementers of its branch committed. Their `records/` and `reports/`, and the implementers' scratch areas; its own `records/` | The project |
| `manager` | Its `repo/` with every branch; the project's `instructions/`; its `reports/`, `sessions/` and scratch area (`…/manager/<name>/`) | The project's history; read-only mounts of workers that existed at this manager's start; every worker's reports and records through `worker-read` | Its `repo/` |

- **Where the project's rules come from.** pi reads `AGENTS.md` from the folder it starts in. An implementer and a manager start in their own copy. A deep reviewer starts in the project, whose rules are yours. A reviewer starts in a folder of its own and gets the project's `AGENTS.md` from the project itself, copied by the launcher at the start: never from the copy it reviews, which the reviewed worker could have changed.
- A reviewer of either kind never sees another reviewer, and no worker but the manager sees another worker's pi sessions.
- **A reviewer sees committed work only, in a clean copy.** At every start of a reviewer the launcher fetches the commits of the reviewed copies into the reviewer's own `repo/`, which runs nothing of those copies, and only that step sees them. The reviewer and its jobs get the clean copy read-only, so git in it never meets a file or a setting that another agent wrote. A reviewer's copy shows the files of the implementer's branch (`worker/<branch>/<name>`); a deep reviewer's shows the project's side branch, with each implementer's branches as `reviewed/<name>/…` and the managers' as `manager/…`, for `git diff`, `git log` and `git show`.
- **A reviewer's folder holds its clean copy,** which counts against the reviewer's own limit. An implementer that commits more than fits there keeps its reviewer from starting, with a message; raise that reviewer's limit (`sudo zfs set quota=<size> <dataset>`) or have the implementer take the large files out.
- **The reviewed code is run through the queue.** In a reviewer's jobs its own `reports/` is read-only, so nothing that the reviewed code does can write the review. Output goes to the scratch area; a test that must write into its own tree is run on a copy there, for example `queue run -- bash -c 'mkdir -p "$WORKER_SCRATCH/tree" && git -C ../repo archive HEAD | tar -x -C "$WORKER_SCRATCH/tree" && cd "$WORKER_SCRATCH/tree" && <command>'`. **The limit:** reviewed code that a reviewer runs directly in its own sandbox, not through the queue, runs with the reviewer's write access to its report; and so does git run inside a folder that reviewed code has written.
- Another worker's mounted folder is visible only if it existed when the sandbox started: each folder is shared by itself, because a file system that appears later below a shared folder would be writable in the sandbox.
- A manager reads any worker's reports or records, whether that worker is older or newer than the manager's session, through `worker-read [--sha256] [--offset <bytes>] <branch>/<name> <reports|records> [<path>]`. A directory is listed as JSON-quoted names. A regular file is read in pieces of at most 256 KiB; the command says the next offset. Other roles are refused by their broker.
- A manager merges a worker that started after it without a restart: `worker-bundle <branch>/<name> > <file>` writes that worker's committed branch `worker/<branch>/<name>` as a git bundle, and `git fetch <file> worker/<branch>/<name>` takes it in. Only what the user's project does not already have travels: the broker reads the project's branches and their recent history from the project itself, never from the worker's copy. Git runs in the copy only in a sandbox of its own, without network and with its hooks and filters off. Fetch only after the command exits 0: a refused bundle can leave a partial file. The limit is `bundleMiB` (1024 MiB); a worker's copy that shares no commit with the project is refused.
- Inside: `WORKER_PROJECT`, `WORKER_BRANCH`, `WORKER_NAME`, `WORKER_ROLE`, `WORKER_SCRATCH`.

**What the launcher refuses**, each with a message:
- a branch that does not exist in the project (creating the branch is what allows workers on it), and an implementer on the main branch (`main`; another name goes into `~/.local/state/workers/<project>/main-branch`);
- a name that runs already or is being started, before anything is written, and a name that was first started under another role;
- a reviewer without an implementer to review;
- a second repository with the same folder name as a project that has workers;
- plain `pi` inside `~/workers` or `~/scratch/workers`, and `--allow` or `--allow-ro` of anything in them or around them;
- any start in a project that contains the workers' folders, which is `~/scratch` itself (a folder inside it is an ordinary project).

**Instructions.** pi gets files added to its system prompt: the role's, which is declared; for a reviewer the project's rules; and the worker's task, `~/workers/<project>/instructions/<branch>/<name>.md`, which the manager writes. The task file starts with the three lines `branch: <branch>`, `name: <name>`, `role: <role>`; if they are not the worker's own, if the file is not a regular file reached without a link, if it is larger than 256 KiB, or if there is none, the worker does not start and nothing is created. The launcher opens the file once and copies it at the start: a later change reaches the worker at its next start. A manager has no task file.

**A repository with protected files** (`config-tool/protected.nix`): in a worker's copy of it the protected files are read-only as well, and the folders above them can be neither renamed nor removed, as in the repository itself; files beside a protected one stay writable. A link in the place of a protected path or of a folder above it stops the start. `--unlock` lifts this for one session; a manager that merges a change to a protected file needs it too.

## An implementer's intent, and your approval

**A new implementer cannot change its copy of the project.** Until you approve its intent, and until the tests that were approved with it have run once on the copy as it is, `repo/` is read-only for it and for its jobs; it reads everything of its role, writes `reports/` and its scratch area, and runs jobs. The launcher says at every such start what is missing.

| Step | Who | How |
| --- | --- | --- |
| The form | The implementer | `reports/intent.md`, from a template that is put there at its first start: the goal, what changes and what does not, acceptance criteria, the tests it is held to, two or more approaches each with trade-offs and steps, a recommendation, open questions |
| Is it complete | The implementer | `intent check` inside its sandbox says what is missing; it is the check that `workers approve` runs |
| The baseline | The implementer | `queue acceptance` runs the tests that the form proposes, taken from the project (below). It can do so while it plans |
| Approval | You | `workers approve <project>/<branch>/<name>`: the form is shown, every line of it behind `|`, on a terminal in a viewer that `q` closes; you give the number of an approach, a note if you like, and type `yes` |
| What was decided | The tool | `records/decision.md` in the worker's folder: the approach with its steps, the tests, your note. The worker reads it and cannot change it |
| After approval | The implementer | `repo/` is writable once the approved tests have run on the copy as it was approved. An open supported pi chat continues automatically in a fresh sandbox; otherwise the next start applies the approval. If the approved list is not the one that ran (the manager added a test, the form changed), the worker stays read-only and says to run `queue acceptance` once more |

- **The lock is a record of the tools,** in `~/.local/state/workers/<project>/approvals/`, which no sandbox can reach. Nothing that a worker writes opens it, whatever the file says and wherever it lies.
- **What is approved is what was shown:** the tool reads the form once, checks, shows and records that one copy, with its fingerprint. `workers approve` on a worker that is approved already changes nothing and says whether the form changed since.
- **A manager's advice:** each manager may write `reports/advice/<branch>/<name>.md` in its own manager folder. Its first four lines are exactly `worker: <project>/<branch>/<name>`, `form-sha256: <digest>`, `task-sha256: <digest>` and `tests-commit: <commit>`. The form digest comes from `worker-read --sha256 <branch>/<name> reports intent.md`; the task digest is of the manager-owned task file; the commit is the project branch commit that supplies the tests. Approval shows each current advice after the form, as the named manager's word with every line behind `|`. A changed form, task or tests commit is named plainly and the old advice is not shown as current; the approval output gives the manager continuation command that renews it. Advice never chooses an approach or opens the lock.
- **A small task:** `workers approve --without-form <project>/<branch>/<name>` opens the lock on your word alone, also before the worker's first start. The record says that it was done so.
- **An open pi chat continues when the lock opens:** a normal interactive saved-chat pi worker finishes and saves its current answer, lets a foreground queued job for that answer finish, stops detached queued jobs with its old broker, and continues the same chat automatically in a fresh writable sandbox. Unsubmitted editor text is restored after continuation. The one request is made when approval and a successful baseline first both exist, whichever arrives last; another baseline for the same approval does not request another continuation.
- **Automatic continuation is deliberately narrow:** unsupported or noninteractive pi options and non-pi workers are left running and the approval prints the exact manual `pi --branch ... --name ... -c` command. A failed baseline records its result but requests no automatic continuation. The supervisor prints manual recovery only if continuation startup fails before the resumed pi session starts; a later non-zero exit is just that session's exit and does not print a false recovery message.
- **`workers approve --revoke`** takes an approval back: read-only again from the worker's next start, and the decision file is removed. It does not mutate a writable sandbox that is already mounted.
- **A test in the form** is `` `<name>`: <reason> `` with the name as the project's test command takes it, `new: <a test that does not exist yet, and its expected result>`, or `none: <reason>`. A manager adds tests in the worker's task file, as lines `test: <name>` directly below its three first lines; the approval shows them apart.
- **Without tests the approval alone opens the lock:** when no existing test is approved, or when the project does not say how its tests are run. The record, the decision file and the command say "no tests", with the reason.
- **`workers approve --empty-scratch`** also returns the worker's scratch area to what it was when the worker was made, empty, so that the work starts from the approved plan and not from what was tried before. Later snapshots of the area go with it. It needs the datasets and a worker that does not run.
- **The limits:** a worker that waits can still write code in its scratch area and move it into its copy afterwards; the lock ensures that you decided before the project copy changes. The check proves that the form is complete, not that the plan is good.
- Reviewers, deep reviewers and managers have no lock.

## The tests a worker is held to

**What a project states once,** in `workers.toml` in its top folder, committed by you:

```toml
[tests]
paths = ["tests"]                              # the folders and files that are the tests
all = ["python3", "-m", "pytest", "-q"]        # runs them all
selected = ["python3", "-m", "pytest", "-q"]   # runs the tests whose names follow it
```

**What you name in `paths` is what the worker cannot change.** Everything else in the run is the worker's commit, also the test tool's own settings: with pytest, a `pyproject.toml`, `pytest.ini` or `conftest.py` in the worker's commit can leave tests out or change what they do. `paths` may name such files beside the test folders; what is not named there is the worker's to change and a reviewer's to read. Every path must exist in the project's commit from which the tests are taken. A missing path fails the acceptance run, with that path named; it does not mean that the worker must leave the path absent.

**`queue acceptance`,** in an implementer's session, runs the approved tests (before the approval: the ones its form proposes). The worker starts the run and chooses nothing of it:

- **The code** is the worker's copy as it is committed on its own branch, `worker/<branch>/<name>`, unpacked in the job's own `/tmp`, which the agent's sandbox does not share. That branch is what its reviewers start from and what the manager fetches, so it is the one commit throughout: what is tested, what the baseline is recorded for, and what `workers status` calls current. Where the copy's files stand at the moment, on another branch or on an older commit, plays no part. The commit is fetched from the copy, so the copy's own git settings, which are in no commit, change nothing of it.
- **The tests** are the project's: the paths of `workers.toml` are taken from the project's history, at the commit of the worker's branch that the approval names, in place of the worker's own. A test that the worker weakened in its copy is not the one that runs.
- **The command** is the project's, from the same commit. Nothing of the environment of the `queue` command reaches it.
- **The record** of the run says `"kind": "acceptance"`, which tests, from which commit of the project, on which commit of the copy, and the exit status. Every run's record also holds the job's highest memory (`memory_peak`) and, if the kernel stopped a process of it for memory, how many (`memory_stops`).

The first such run on the copy as it was approved is the **baseline**; the lock opens with it (above). A baseline that fails still counts: the record shows that the tests failed before the work began. It does not trigger automatic continuation; the user can use the exact manual continuation command after deciding how to proceed, or a later successful baseline can trigger the one automatic continuation.

**`queue acceptance --all`,** in a manager's session, runs the project's whole suite on the manager's copy as it is committed, with that copy's own tests: the merged result, with the tests that the workers added.

**The limits:** the tests run with the worker's code in one job, in the worker's own Python environment; code that is written to make a test pass without doing the work is for the reviewer to find. What is tested is what is committed.

## The reviews' way back

When a reviewer or a deep reviewer is started, the launcher writes down which implementer it reviews and from which commit. At that implementer's next start it has the `reports/` folder of each such reviewer in its view, read-only, at `~/workers/<project>/<branch>/<reviewer>/reports/`; a verdict is the first line of `review.md` there. A round of corrections is therefore a new start of the implementer. Another implementer does not see those folders.

## How work travels

Every implementer has a complete copy of the project with its own history files, so two workers never write the same files on disk. What can happen between them is a conflict when their work is merged, never damage.

| Step | Who | How |
| --- | --- | --- |
| A side branch exists in the project | You | `git branch boundary`; that is what allows workers on it |
| A copy, on a branch of the worker's own (`worker/<branch>/<name>`) | The launcher, at the worker's first start | Inside the worker's sandbox |
| Commits | The implementer | In its copy only; with your git identity, and no worker's name in a commit |
| Merging workers into a side branch, and side branches into each other | The manager, in its copy | `git fetch ~/workers/<project>/<branch>/<name>/repo worker/<branch>/<name>:refs/workers/<branch>/<name>`, then `git merge` |
| A worker gets merged or published work | The implementer | `git fetch manager` (the manager's copy is a remote of every copy), or `git fetch origin` for your own commits |
| The result, prepared for you | The manager | On the main branch of its copy |
| Into the project | You | `workers take` in the project: the manager's main branch arrives as one change set, **staged and not committed** |
| A side branch that the manager prepared | You | `workers take --branch <name>`: its content arrives the same way, staged on that branch of the project. The branch is made if the project does not have it, from the commit it shares with the main branch; the project is on that branch afterwards |
| Review, commit, push | You | `git diff --cached`, `git commit`; or send it back with the command that `workers take` names |
| Afterwards | The manager | `git fetch origin && git merge origin/main` (or `origin/<name>`), so that its copy holds your commit |

- **Every commit in the project is yours:** `workers take` squashes, for the main branch and for a side branch. The workers' own histories stay in the copies.
- `workers take` also says what the manager's records hold about the project's whole suite on the commit it brings: that it passed, that it failed, or that no such run is recorded. It stages the change in each case; the judgement is yours.
- A side branch exists in the project from the moment `workers take --branch` made it, at its starting commit. A worker that is started on it before your commit does not have the staged work.
- After `workers take` the message of your commit is yours alone: git would otherwise propose the messages of the copies' commits, which name workers' branches.
- git never runs outside a sandbox in a folder an agent writes. The tools only fetch from a copy, which runs nothing of it; the launcher makes a copy inside the worker's sandbox.

## Bringing in an existing project

A project that you worked on before has work that is not committed, and branches that nobody sorted. A manager sees only what is committed, so:

```bash
cd ~/projects/<project>
workers found                      # the work as it lies there, on a new branch found/<date>; every stash on a branch beside it
pi --role manager                  # its copy holds those branches; sort the work into side branches with it
workers take --branch <name>       # each side branch you want, staged for your commit
```

- `workers found` makes one commit of yours from the tracked changes and the untracked files, and changes nothing of the working tree, the index or the current branch. With that branch as a record you can clean the working tree afterwards, which `workers take` asks for.
- Left out, and named: untracked files larger than `foundLargeMiB` (10 MiB), unless you add `--with-large-files`; they would stay in the history for good. Files that the project ignores are never recorded.
- To show a manager the ignored files too, read-only: `pi --role manager --allow-ro ~/projects/<project>`.
- A folder that is no repository yet: `git init` and a first commit of yours come first.
- A project is named by its folder, wherever it lies. The folders above it must not be repositories themselves: a project without its own `.git` would be taken for the repository around it.

## What the workers are doing

```bash
workers status           # a table: every worker, where it stands, what it uses, its tests, its reviews, and its own word
workers status --json    # the same as one document, which the live overview reads
workers watch            # the live overview in the terminal; it only displays, and q ends it
```

The document's form is `workers-dashboard/SCHEMA.md`. The overview makes one block per project. Managers are indented two spaces below the project; each side branch is indented two spaces and its implementers, reviewers and deep reviewers four. One blank line separates branches and two separate projects. Names receive room before optional measurements, roles are written in full, and a long item in work uses at most two lines. A reviewer appears once under its branch and names every implementer it reviews. Ordinary sessions share one final block. A project without a manager is shown in the same form without a manager row.

A worker's detail names the paths supplied by the status command for its copy, reports, records, task file and scratch area. It remains a separate view: opening the full detail below a selected row would displace the surrounding branches in a busy overview, especially when work already wraps. The overview does not construct paths. An ordinary session has no worker folder; its detail says so, and still names its run records and scratch area when they are known. Resource meters appear only from 70% of a known limit; lower values are plain figures. Yellow means warning and red means trouble. Magenta is reserved for a future `needs you` state, which the current document cannot report.

**Every value says where it comes from,** and an agent's own words stand apart:

| Kind | What | From |
| --- | --- | --- |
| Measured | Whether a worker runs; its memory and processor time and its jobs'; the sizes of its folder and scratch area; processes that were stopped for memory | The system's accounting of the resource groups and the datasets |
| Recorded | The queued runs with their exit status and commit; the approved tests' last whole run (`passed`, `failed`, `stale` when it passed on an older commit, `never run`); the approval | The broker's records and the tools' own |
| Derived | Commits ahead of and behind its branch in the project; how many reviewers were started against it, and how many of them on an older commit; where it stands (below) | Computed by the tool, with a copy only ever asked as a remote |
| Self-reported | Whether there are uncommitted changes | Asked inside the worker's own view, at its last run |
| Claimed | The agent's to-do list; its one line in `reports/status.md`; a reviewer's verdict, the first line of its `reports/review.md`; "ready for review" | The agent's own words |

- **A claim never changes a fact.** A worker that writes "passed" changes the last column and nothing else; whether the approved tests passed is the broker's record.
- **The to-do list** is read from the worker's newest pi session file: the last entry that the to-do extension wrote there. If that entry is not in the form this tool knows, the list is left out and the command says so.
- **An ordinary session's shared data is not assigned to it.** All ordinary sessions of one project currently share one session folder and one run-record file, so the status document leaves their to-do lists and runs out rather than guessing which session owns them. It still shows their shared records path and scratch path. Worker-only facts in their detail are stated as facts they do not have, not as an ambiguous dash.
- **The next command** is composed by `status.py`, marked `derived`, and shown without being run. It is present when an implementer waits for approval or a reviewer, and when a merged worker can be removed.
- **A reviewer** names every implementer it has reviewed and whether `workers remove --merged` would take it now. A manager and a deep reviewer say that their own explicit command removes them.
- **What an agent wrote is read as data:** without following a link, within a size limit, each text cut to 4096 bytes. Nothing of it is run.
- **Stopped for memory:** how often is the watcher's count. Which job it was is in that job's record (`memory_stops`, beside `memory_peak`, the job's highest memory). Which agent it was is known only if the agent's sandbox still ran two seconds later.
- On a machine with plain folders the sizes of folders and scratch areas are left out.

**Where an implementer stands:**

| State | When |
| --- | --- |
| `planned` | It is not approved |
| `approved` | It is approved and has no commit of its own yet |
| `implementing` | Its lock is open and its branch holds commits that the project's branch does not |
| `ready for review` | The same, and its line in `reports/status.md` starts with those words. This is the one state that rests on the agent's word, and it is marked as claimed |
| `reviewed` | A reviewer that was started from its current commit has written a `reports/review.md`. That the file is there is a fact; what it says stays the reviewer's word. A reviewer that was only started changes nothing, and neither does a review of an older commit |
| `merged` | It has commits of its own, and the project or a manager's copy holds every one of them |
| `removable` | Merged, its last queued run reported nothing uncommitted, and it does not run |

- **Under the table** `workers status` prints, for every implementer whose work waits for a review, the command that starts its next reviewer, under a name that is free, and where the manager writes that reviewer's task file first.
- **The tools' own repository** (`~/.local/state/workers/<project>/mirror.git`), in which the commits are counted, holds of a copy what the copy's branches hold and no more: when a worker moves a branch back or aside or deletes one, what that leaves behind is removed at the same call. One count works in it at a time. On the first status of a project with many branch references, the display answers first with the commit counts as "not known yet" and starts one detached count; a later status replaces them with the result. An old count is not shown as current while that refresh is needed.

## Workers that exist, and removing one

```bash
workers list                                  # every worker: role, running or not, sizes, commits that nobody else holds
workers remove <project>/<branch>/<name>      # refused while it has uncommitted changes or such commits; --force overrides
workers remove --merged <project>             # removable implementers, then reviewers whose implementers are all removed
workers restore <project>/<branch>/<name>     # within 14 days
workers remove-session <project>-<digest>     # the scratch area and records of a project's ordinary sessions
```

A removal archives the worker's records, reports and task file in `~/workers/<project>/archive/`, destroys its scratch area, and unmounts and marks its folder. It either completes or leaves the worker as it was: while a terminal or a program is in the worker's folder or scratch area it is refused, and can be repeated afterwards. Whether a copy has uncommitted changes is asked of git inside a closed sandbox that holds only that copy, for at most `questionSeconds` seconds; the answer is the copy's own word, since its settings can hide files, and the folder is kept for the holding time all the same. The folder is kept for `hostSpec.workers.holdDays` days (14) and can be restored with everything in it; its name stays taken meanwhile. Only a timer of the system destroys a folder, once its mark is that old: no command of yours, and so no program running as you, can.


- **`removable`** in the list's STATE column: an implementer whose work is merged (see the states above), whose last queued run reported nothing uncommitted, and that does not run.
- **`workers remove --merged <project>`** removes each such implementer by the removal above, which can be undone. It asks the two questions again at that moment; a worker that fails them is left, and every implementer that is left is named with the reason. It then checks the reviewers afresh: a reviewer is removed only once every implementer it was started against is removed. A reviewer that stays is named with the reason, including missing review records. Managers and deep reviewers are not removed by it.
- **Once a week** (Monday 09:00, or at the next login after it) a desktop notification says how many workers are removable and how much space they hold, and names the command. It removes nothing.
- **A manager's own commits** count as held when the project or another manager's copy has them. A squash counts too: when a manager's current branch tip has exactly the same tree as a commit reachable from a branch in the project, its history is held. No separate record of a take is kept. A later manager commit is not covered by that match; resetting the project's branches so that the matching commit is no longer reachable withdraws it.
- **Remove in this order:** review and commit the taken work in the project; run `workers remove --merged <project>` while the manager's copy still holds the implementers' histories; remove deep reviewers explicitly when no longer needed; remove the manager last. An uncommitted take does not hold the manager's work.
- **Removal is one transition:** a project lifecycle lock serializes starts with removal. Every running session records which other workers' places it mounted; if one holds the target, removal refuses before creating an archive or detaching a dataset and names the holder. If scratch destruction fails after detaching, the helper restores the folder properties and both mounts and the tool removes the tentative archive. A worker left half removed by an older version remains retryable: the next call finishes it once the real holder is gone.
- **What goes with a worker:** its approval is set aside at the removal and comes back with `workers restore`. When the timer has destroyed the folder, the tools' records of the worker go at the next `workers` command, and the name is free for a new worker, which starts without an approval. A task file of that name in `instructions/` stays where it is (its copy is in the archive): the manager writes the new worker's task over it.
- **A sandbox's runtime state** (`$XDG_RUNTIME_DIR/workers/<unit>/` with the view and the socket, and the copies of the task file and the project's rules beside it) is removed when the sandbox has ended. A start that comes while the last sandbox of the same worker is still ending waits for it, at most ten seconds.

## Ordinary sessions

`pi` without worker options works as before in the project, and is one more agent: it has a broker, the agents' limits, and a scratch area of its own, `~/scratch/workers/<project>-<digest>/plain/session/`, where uv's downloads and other caches go instead of the home in memory. Caches therefore outlive a session: a later session of the same project, or of the same worker, reads what an earlier one left there. That is the same trust as the project folder itself, and it never crosses from one worker to another. The digest is of the project's path, so two projects with the same folder name never meet. Its run records are in `~/.local/state/workers-plain/<project>-<digest>/`, kept within about 2 MiB.

## Limits

Every place a worker can write returns an error when it is full; nothing is stopped.

| Place | Limit |
| --- | --- |
| The worker's folder | `folderQuota`, default 10 GiB. Its snapshots count: a worker that writes and deletes large files in `repo/` fills its folder until the snapshots expire; large output belongs in the scratch area |
| The scratch area | `areaQuota`, default 50 GiB |
| The task files | `instructionsQuota`, default 1 GiB |
| `/tmp`, the home folder, `/run` and `/dev/shm` in the sandbox, which are memory | `tmpfsMiB`, default 1024, 1024, 64 and 1024 MiB; they count towards the agent's memory, or the job's |
| The rest of `/dev`, the sandbox's top folder, and `/run/worker` with the broker's socket | They take no file at all. A program that wants a folder of its own directly under `/`, such as `/var/tmp`, does not get one: `/tmp` is there for that |

**A worker stuck at its folder's limit because of snapshots:** list them with `zfs list -t snapshot -o name,used rpool/workers/<project>/<branch>/<name>` and destroy the ones holding the deleted files with `sudo zfs destroy <snapshot>`; or wait until they expire.

The totals for `~/workers`, scratch, the Nix store and the home are the host's (`hostSpec.disk`).

## The queue

Heavy work goes through `queue`. An agent's own sandbox has a small budget; a queued job gets the machine's.

| Command | Meaning |
| --- | --- |
| `queue run -- <command>` | One of `hostSpec.workers.slots` slots, on the whole machine |
| `queue run --parallel -- <command>` | Also one of the `parallelTokens`, for a command that runs concurrent processes itself |
| `queue timing -- <command>` | One timing job at a time, alone on the timing cores (below) |
| `queue exclusive -- <command>` | The whole machine: waits until no queued job runs, and holds new ones back |
| `queue acceptance` | An implementer: the approved tests, from the project, on its copy as committed. With `--all`, a manager: the whole suite (see "The tests a worker is held to") |
| `queue status` | Which slots are taken, and whether the timing cores are reserved |

- **Where a job runs.** Every sandbox has a broker, a small program outside it. The broker waits for the slot and starts the job in a second sandbox with exactly the worker's view, in a resource group of its own. Nothing of a request is used outside that job sandbox or rewritten on the way, and whatever is not exactly a request is refused. A job gets the environment of the `queue` command that started it, except variables whose names are not plain names, such as a shell's exported functions; `queue` says which it left behind.
- **Network:** all sandboxes share the machine's network, including loopback and listening ports. They are not isolated from each other by a network namespace. Do not use a local listening port as a private channel between a worker and its jobs.
- **What a job shares with its worker:** files and the machine's network. It has its own `/tmp` and its own processes. A job ends when its command ends: a process that the command left behind, such as a server, is stopped then, and what it printed until then is saved. Waiting for a slot counts against the time limit of the agent's command tool.
- **Output.** The job's output and errors go, as two streams, to the `queue` command that started it. What it prints is also saved with the run, in `$WORKER_SCRATCH/runs/<id>/output.log` (`$QUEUE_RUN_DIR` is that folder). The saved printout is the worker's own file: it and its jobs can change or delete it. It is not protected evidence like the broker's run record. Many commands only print and write no result file; an agent that saw a long printout cut off can read the rest instead of running the command again.
- **Record.** The broker writes to `records/runs.jsonl` in the worker's folder, which the worker can only read. Every job has a line from before it starts (`"state": "started"`: the command, the folder, the start, the waiting time, and the commit the worker's copy was at, which the broker asks from outside) and a second line with the same `id` at its end (also the duration, the exit status, and whether it was stopped). No job runs without the first line: when the worker's folder is full, `queue` refuses and says so. A run whose last line is the first one still runs, or its end could not be written, which `queue` also says. Whether there were uncommitted changes is the worker's own word and is named so (`uncommitted_as_reported`).
- **Ends.** A job ends when its command ends, when its `queue` command is stopped, when the sandbox ends, and when the broker ends. Without a broker, `queue` refuses and runs nothing. Inside a job, `queue` runs its command directly.
- **A longest run time** per mode can be set (`maxRunSeconds.run`, `.timing`, `.exclusive`); it is off. A job beyond it is stopped, `queue` says so, and its record has `"time_limit": true`.
- **One sandbox's share:** at most `maxSlots` ordinary jobs hold queue slots at once, including acceptance and `run --parallel`. Requests beyond that wait without holding a global slot or parallel token, so another sandbox can use the remaining slots. Timing and exclusive jobs keep their separate rules.
- **One ordinary job's processors:** `jobProcessors` limits total processor time of a `run` or acceptance job and all its children, enforced by the kernel. It is a quota, not a fixed set of CPUs. `run --parallel`, timing and exclusive jobs do not have this quota; timing still uses only its reserved cores.
- **Slots** are empty files of root's in `/run/worker-queue`, which no sandbox sees. A broker holds one by a file lock; the kernel drops the lock when the broker ends, and a reboot starts with new files.

## Memory and cores

| Limit | Option | What happens at the limit |
| --- | --- | --- |
| All sandboxes, brokers and jobs together | `totalMemory`; `processorWeight` against the user's other resource groups; they have no swap | The kernel stops a process at the memory limit; under CPU contention, the desktop's default weight gets the larger share |
| All agents together, without their jobs | `agentsMemory`, `agentsCpuQuota` | A process of an agent is stopped; the agents share that much processor time |
| One agent's sandbox, its folders in memory included | `agentMemory` | A process in it is stopped; the agent's shell survives |
| One broker | `brokerMemory` | |
| Nix builds, which run in the Nix daemon and not in any sandbox | `nixDaemonMemory`; never on the timing cores; behind interactive work | |

Every stop for memory is written to the journal of `workers-memory-watch` in the user's systemd and shown on the desktop; so is a reservation of the timing cores that outlived its timing job. A plain `pi` counts as an agent like every other.

### Every number, in one place

All of them are options of `hostSpec.workers`, set in one block of the host's file under `modules/hosts/`; the programs hold no number of their own. Change one there and rebuild. Those with a command in the last column can also be changed until the next restart of the session.

| Option | What it limits | Laptop | Until the next restart |
| --- | --- | --- | --- |
| `totalMemory` | Memory of all sandboxes and jobs together | 18G | `systemctl --user set-property --runtime workers.slice MemoryMax=20G` |
| `agentsMemory` | Memory of all agents together, without their jobs | 6G | `systemctl --user set-property --runtime workers-agents.slice MemoryMax=8G` |
| `agentMemory` | Memory of one agent's sandbox | 3G | `systemctl --user set-property --runtime worker:<project>:<branch>:<name>.scope MemoryMax=4G`, for one that runs |
| `agentsCpuQuota` | Processor time of all agents together; 100% is one CPU | 400% | `systemctl --user set-property --runtime workers-agents.slice CPUQuota=600%` |
| `processorWeight` | Relative share of contended processors for the whole worker group; the desktop default is 100 | 20 | `systemctl --user set-property --runtime workers.slice CPUWeight=30` |
| `brokerMemory` | Memory of one broker | 64M | |
| `nixDaemonMemory` | Memory of Nix builds | 12G | `sudo systemctl set-property --runtime nix-daemon.service MemoryMax=16G` |
| `slots`, `parallelTokens` | Jobs of `queue run` at once; of those, with `--parallel` | 5, 1 | |
| `maxSlots` | Ordinary queue slots held by one sandbox, including acceptance and parallel jobs | 2 | |
| `jobProcessors` | Processor time of one ordinary run or acceptance job, in CPUs; not parallel, timing or exclusive | 2 | |
| `maxRequests` | Requests of one sandbox waiting or running | 8 | |
| `maxRunSeconds` | Seconds a job of a mode may run; 0 is no limit | 0, 0, 0 | |
| `timingCpus`, `workCpus` | The timing cores and all others | 0-3, 4-27 | |
| `tmpfsMiB` | `/tmp`, home, `/run` and `/dev/shm` of a sandbox, in MiB. An acceptance run needs room in `/tmp` for the tested commit's history and its files together | 2048, 1024, 64, 1024 (default 1024 for `/tmp`) | |
| `folderQuota`, `areaQuota`, `instructionsQuota` | One worker's folder, one scratch area, a project's task files | 10G, 50G, 1G | `sudo zfs set quota=<size> <dataset>`, for one that exists |
| `holdDays` | Days a removed worker's folder is kept | 14 | |
| `foundLargeMiB` | Above this size `workers found` leaves an untracked file out | 10 | |
| `questionSeconds` | Seconds `workers remove` waits for git's answer about a copy | 60 | |

What holds now: `systemctl --user show -p MemoryMax -p CPUWeight workers.slice` and `systemctl --user show -p MemoryMax -p CPUQuotaPerSecUSec workers-agents.slice`. The totals of the disk (the home's reservation, the Nix store, scratch, `~/workers`) are in `hostSpec.disk` of the same file.

**Timing cores** (`timingCpus`, with `workCpus` for all others; whole physical cores). They are shared normally. While a `queue timing` job runs, everything else of the user is moved to the other cores: the desktop's programs, the agents, the other jobs, and whatever else runs in a slice of the user's systemd at that moment, including programs that were already running. When the job ends they get all cores back. If the broker of a timing job ends before it gave them back, the cores stay reserved, `queue status` says so, and the next timing job that ends lifts it. Not moved: the login session's own start-up processes, system services other than the Nix daemon, and the kernel.

## Snapshots of a scratch area

```bash
pi --branch boundary --name paired-conditions --snapshot before-sweep
pi --branch boundary --name paired-conditions --snapshots
pi --branch boundary --name paired-conditions --rollback before-sweep   # later snapshots of the area are destroyed
```

They run outside the sandbox and touch one area. A worker's folder is snapshotted by sanoid with the rule of `rpool/workers`, and is in the backup.

## The helper

ZFS lets only root mount a dataset, so the launcher and the `workers` command call `worker-datasets` through `sudo`; the user may run that one program without a password, and a sandbox has no working `sudo`. It builds dataset names and mount points from checked names, and acts only while both parents are their datasets, mounted, with a top folder that belongs to root. What it does for a caller is creating, mounting, snapshotting a scratch area, and removing a worker in the way that can be undone; making a project's knowledge place (`ensure-knowledge <project> <branch>`: `knowledge/common/` and `knowledge/<branch>/`, each a dataset owned by the user with a worker folder's limit, snapshotted and backed up, below folders that belong to root; `knowledge` is therefore no branch name for workers); it destroys scratch areas, which hold only what can be made again, and never a worker's folder. Without the two datasets (the test VM) the same paths are plain folders, without limits, snapshots and removal.

## Validation

The `workers-queue` check runs in a virtual machine with the launcher running a shell: two jobs on one slot; one sandbox's slot allowance while another starts a job; a multi-process job's CPU quota and an uncapped parallel control; a job's sandbox against the agent's; what a job can reach; requests that are not exactly requests, that cannot be read, or that arrive too slowly; an environment that names programs; a job whose command leaves a process behind, and one whose output is read slowly at its end; the ids of runs that follow each other within a second; the limits of requests, memory and processor time; a killed sandbox, client and broker; 2 GiB of output; the timing cores before, during and after a timing job and after a killed broker; a Nix build; a reboot.

The `workers-git` check: an implementer's copy on its own branch, with history files of its own; that neither an implementer nor a manager can write the project; merging in the manager's copy, fetching from it, `workers take` with its refusals and a second round; `workers take --branch` for a new branch, a second round, its refusals and the way back; `workers found` with changed, staged, untracked, ignored, stashed and large files; `workers list` and the checks of a removal, including a manager whose work was taken and committed, later manager work and a reset of the project; reserved branch names in `take`; a copy with planted hooks and settings, with `.git` made anew, as a link and with a `commondir` file, against everything that touches it from outside a sandbox; a copy of a repository with protected files, the folders above them, and links in their place; the same protection inside the jobs of an ordinary session; a job beyond a time limit.

The `workers-roles` check: the project found by its path when its git settings name another folder; every refusal of the launcher, including reserved branch names at a start and at approval; an ordinary session's scratch area and records; the role's file and the task file as a command's arguments, including the tool-owned manager and implementer guidance; a task file for another worker, a link, a file too large, a change after the start, and a second start meanwhile; what a reviewer, a deep reviewer and the manager read and write; an implementer before and after its approval, forms that are not complete, manager advice bound independently to the form, task and tests commit, a form changed while the user is asked, a form that imitates the tool, the viewer on a terminal, and what a worker forges; the approved tests against a weakened test in the worker's copy and against a filter in the copy's git settings, both approval/baseline orders, one continuation request, a failed baseline, the baseline as part of the lock, and what `queue acceptance` refuses, including a named missing test path; the same against a copy whose files stand on another commit than its branch; the status document for every role with a running job, against the resource groups' own numbers and against the dashboard's reader, with an agent's text in every place it reads, and a sample of the to-do extension's entries; every state of an implementer in turn; status calls at the same moment, a fetch that fails once, and a worker that drops large commits again and again; a reviewer's report in its implementer's view; an implementer that plants a program in its copy's git settings and a test that writes into reports, against a reviewer's way of working; pi itself started in every role without a network; automatic continuation startup versus a later session exit; inherited restart descriptor verification; and tools of a development shell.

The `workers-layout` check runs in two virtual machines with the launcher running a shell: the helper against a caller that replaces a parent by a link or by a folder of its own, that passes names reaching outside, and that tries to swap a folder while the helper runs; the datasets, owners and limits after a first start; what an implementer and a manager can read and write; a worker created after the manager started; snapshot and rollback; every place that the sandbox itself lists as writable, filled until it returns an error, by the agent and by a job; a job with the worker's folder full; removal with the folder or scratch area in use, a manager mount holder named before change, a controlled start-versus-removal race, rollback after scratch destruction fails, and completion of an older half removal; `workers remove --merged` with a merged worker, an unmerged one and one that fails the question, and the reminder; reviewers of removed and remaining implementers, including one that reviewed both; a user-made `old` folder left intact and a refused branch of that name; the tools' records after the timer destroyed a folder; a scratch area emptied at an approval; the backup's list and sanoid's snapshots; a reboot; and plain folders. The `backup` check holds a file in a worker's folder.

**No test waits a fixed time for another side to be ready:** it waits for the condition, or the other side waits at a gate that the test opens. On a machine with hardware virtualisation every bound that is measured in seconds is as tight as it was. Inside a build on a host without it (Nix's build users on the Ubuntu machine have no KVM) the test machines are emulated and many times slower; the tests notice that, let what has to last (a job that another one must meet) last ten times as long, and give the bounds more room. They pass there too, and take much longer. Two of the checks run the dashboard's reader on the status document; the dashboard is built from `workers-dashboard/` of this repository, and its own tests are the check `workers-watch`.

Through the drivers, with KVM:

```bash
nix build 'path:'"$PWD"'#checks.x86_64-linux.workers-layout.driver' && ./result/bin/nixos-test-driver
nix build 'path:'"$PWD"'#checks.x86_64-linux.workers-queue.driver' && ./result/bin/nixos-test-driver
nix build 'path:'"$PWD"'#checks.x86_64-linux.workers-roles.driver' && ./result/bin/nixos-test-driver
nix build 'path:'"$PWD"'#checks.x86_64-linux.workers-git.driver' && ./result/bin/nixos-test-driver
```
