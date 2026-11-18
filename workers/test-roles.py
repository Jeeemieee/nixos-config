import calendar
import hashlib
import json
import re
import shlex
import time

home = f"/home/{user}"
folders = f"{home}/workers"
areas = f"{home}/scratch/workers"


def asUser(command):
    """Run a command as the user, outside any sandbox"""
    environment = f"HOME={home} USER={user} XDG_RUNTIME_DIR=/run/user/1000 PATH=/run/wrappers/bin:/run/current-system/sw/bin"
    # Its input is closed off: sudo forwards its input to the command, and here that input is the channel of the test driver's own commands
    return f"sudo -u {user} env -i {environment} bash -c {shlex.quote(command)} < /dev/null"


def approved(project, branch, name):
    """The user's word that opens an implementer's copy without a written intent, given once: the tests of the lock are in workers-roles"""
    record = f"~/.local/state/workers/{project}/approvals/{branch}/{name}"
    return f"[ -e {record} ] || printf '\\nyes\\n' | workers approve --without-form {project}/{branch}/{name} > /dev/null 2>&1; "


def implementerOf(options, project):
    """The approval for the implementer that these options start, if they start one"""
    names = re.search(r"--branch (\S+) --name (\S+)", options)
    if (names is None) or ("--role" in options):
        return ""
    return approved(project.rstrip("/").split("/")[-1], names.group(1), names.group(2))


def start(options, script=None, project="~/alpha", launcher="worker-shell", prefix="", locked=False):
    """Start a sandbox in a project with the launcher's options; with a script, the stand-in is a shell that runs it"""
    command = ("" if locked else implementerOf(options, project)) + f"cd {project} && {prefix}{launcher} {options}"
    if script is not None:
        command += f" -c {shlex.quote(script)}"
    return asUser(command)


def refused(options, reason, **arguments):
    out = machine.fail(start(options, "true", **arguments) + " 2>&1")
    assert reason in out, f"{options}: {out}"
    return out


def gate(name):
    """Inside a sandbox or a job: wait here until the test lets it go on, with openGate()"""
    return f'until [ -e "$WORKER_SCRATCH/{name}" ]; do sleep 0.2; done'


def openGate(worker, name):
    """Open a gate of a worker, <project>/<branch>/<name>"""
    machine.succeed(f"touch {areas}/{worker}/{name}")


def sandboxEnded(worker, timeout=30):
    """Wait until the sandbox of a worker that was seen running has ended"""
    machine.wait_until_succeeds(asUser(f"! systemctl --user is-active --quiet worker:{worker.replace('/', ':')}.scope"), timeout=timeout * pace)


machine.start()
machine.wait_for_unit("multi-user.target")
machine.wait_for_unit("user@1000.service")
# Inside a Nix build on a host without hardware virtualisation this machine is emulated, and many times slower. Nothing here
# waits a fixed time for another side to be ready: it waits for the condition, or the other side waits at a gate. What has to
# last, a job that another one must meet, lasts `pace` times as long on an emulated machine; and what is measured in seconds
# has more room there, while on a machine with hardware virtualisation every bound is as tight as it was
emulated = machine.succeed("systemd-detect-virt").strip() != "kvm"
pace = 10 if emulated else 1
# Real pi can be CPU-starved by busy host workers even with KVM, so input waits for its rendered provider prompt with this longer startup-only bound; every behavioral assertion stays unchanged
realPiTimeout = 300 * pace
print("emulated:", emulated, "pace:", pace)
repository = 'git init -q -b main {0} && echo content > {0}/file && echo "rules of the project" > {0}/AGENTS.md && git -C {0} add . && git -C {0} -c user.name=t -c user.email=t@t commit -q -m base && git -C {0} branch b1 && git -C {0} branch b2 && git -C {0} branch old'
machine.succeed(
    asUser(
        "mkdir -p ~/.ssh ~/other ~/group/sibling && echo secret > ~/.ssh/id_test && echo beside > ~/group/sibling/file && "
        + " && ".join(repository.format(path) for path in ["~/alpha", "~/other/alpha", "~/group/project", "~/x-y", "~/x"])
        + " && git -C ~/x-y branch z && git -C ~/x branch y-z && mkdir -p ~/scratch/own"
    )
)
# A project that states how its tests are run: each test is a script, and the command takes the names of the ones to run
tested = {
    "workers.toml": '[tests]\npaths = ["tests"]\nall = ["bash", "tests/run.sh"]\nselected = ["bash", "tests/run.sh"]\n',
    "src/sum.sh": 'echo $(($1 + $2))\n',
    "tests/run.sh": (
        'status=0\nif [ "$#" = 0 ]; then for file in tests/t-*.sh; do name=${file#tests/}; set -- "$@" "${name%.sh}"; done; fi\n'
        'for name in "$@"; do if bash "tests/$name.sh"; then echo "pass $name"; else echo "FAIL $name"; status=1; fi; done\nexit $status\n'
    ),
    "tests/t-sum.sh": '[ "$(bash src/sum.sh 2 3)" = 5 ]\n',
    "tests/t-env.sh": '[ -z "${CHEAT:-}" ]\n',
    "tests/t-slow.sh": f'sleep {4 * pace}\n[ "$(bash src/sum.sh 1 1)" = 2 ]\n',
}
machine.succeed(asUser("git init -q -b main ~/tested && mkdir ~/tested/src ~/tested/tests"))
for path, content in tested.items():
    machine.succeed(f"printf '%s' {shlex.quote(content)} > /tmp/part", f"install -o {user} -m 644 /tmp/part {home}/tested/{path}")
machine.succeed(
    asUser(
        "cd ~/tested && git add . && git -c user.name=t -c user.email=t@t commit -q -m base && git branch b1"
        # A branch whose workers.toml says nothing usable, and one that names a path the project does not have
        " && git checkout -q -b b2 && printf '[tests]\\npaths = \"tests\"\\n' > workers.toml && git -c user.name=t -c user.email=t@t commit -q -a -m broken"
        " && git checkout -q -b missing main && printf '[tests]\\npaths = [\"tests\", \"missing-test\"]\\nall = [\"bash\", \"tests/run.sh\"]\\nselected = [\"bash\", \"tests/run.sh\"]\\n' > workers.toml"
        " && git -c user.name=t -c user.email=t@t commit -q -a -m missing-path && git checkout -q main"
    )
)

reservedStartProblems = {}
reservedApproveProblems = {}

with subtest("F1: a project whose git settings name the folder above it is still only itself in the sandbox"):
    machine.succeed(asUser("git -C ~/group/project config core.worktree ~/group"))
    # Control: git would answer with the folder above
    assert machine.succeed(asUser("cd ~/group/project && git rev-parse --show-toplevel")).strip() == f"{home}/group"
    out = machine.succeed(start("", 'ls ~/group; cat ~/group/sibling/file; echo "sibling=$?"', project="~/group/project") + " 2>&1")
    print("F1:", out)
    assert out.split()[0] == "project" and "sibling=1" in out and "beside" not in out, out

with subtest("V8: what the launcher refuses at the start"):
    machine.succeed(start("--branch b1 --name i1", "echo of-i1 > file-of-i1; echo report-of-i1 > ../reports/r; echo data-of-i1 > $WORKER_SCRATCH/d; echo session > ~/.pi/agent/sessions/s"))
    refused("--branch nope --name x", "has no branch 'nope'")
    refused("--branch b1 --name 'a b'", "must be 1 to 48 letters")
    refused("--branch b1 --name ../x", "must be 1 to 48 letters")
    refused("--branch main --name x", "main branch")
    for branch in ["manager", "archive", "instructions", "plain", "old"]:
        status, out = machine.execute(start(f"--branch {branch} --name reserved-{branch}", "true", locked=True) + " 2>&1")
        if (status == 0) or ("cannot be a branch name" not in out):
            reservedStartProblems[branch] = (status, out)
    refused("--branch b1", "needs --name")
    refused("--name x", "needs --branch")
    refused("--role manager --branch b1", "belongs to no branch")
    refused("--role root --branch b1 --name x", "unknown role")
    refused("--role reviewer --branch b1 --name r0", "needs --of")
    refused("--role reviewer --branch b1 --name r0 --of nobody", "no implementer b1/nobody")
    refused("--branch b1 --name x --of i1", "--of belongs to the role reviewer")
    # A name keeps its role
    refused("--role reviewer --branch b1 --name i1 --of i1", "is a implementer, not a reviewer")
    # A name that runs is taken
    # (the first one says when its sandbox runs, and waits at a gate)
    machine.succeed(f"({start('--branch b1 --name i1', 'echo sandbox-runs; ' + gate('v8-go'))}) > /tmp/v8-first 2>&1 &")
    machine.wait_until_succeeds("grep -q sandbox-runs /tmp/v8-first", timeout=30 * pace)
    refused("--branch b1 --name i1", "end its running session first to restart this worker, or choose another name with --name <name> for a new worker")
    openGate("alpha/b1/i1", "v8-go")
    sandboxEnded("alpha/b1/i1")
    # The workers' folders are entered through a worker, and shared by role only
    refused("", "is entered through its worker", project=f"{folders}/alpha/b1/i1/repo")
    refused("", "is entered through its worker", project=f"{areas}/alpha/b1/i1")
    for folder in [f"{folders}/alpha/b1/i1", f"{areas}/alpha", folders, areas]:
        refused(f"--allow {folder}", "the workers' folders are shared by role")
        refused(f"--allow-ro {folder}", "the workers' folders are shared by role")
    refused("--allow ~/scratch", "it contains the workers' folders")
    # Control: another folder of the home is still shared on request
    machine.succeed(start("--allow-ro ~/group/sibling", "cat ~/group/sibling/file") + " | grep -qx beside")
    # A second repository with the same folder name cannot have workers, but ordinary sessions start in both
    out = refused("--branch b1 --name z", "has the same folder name", project="~/other/alpha")
    print("V8 same folder name:", out)
    for project in ["~/alpha", "~/other/alpha"]:
        machine.succeed(start("", 'queue run -- true; echo x > $WORKER_SCRATCH/x; test "$XDG_CACHE_HOME" = $WORKER_SCRATCH/cache && test "$UV_CACHE_DIR" = $WORKER_SCRATCH/uv-cache', project=project))
    sessions = machine.succeed(f"ls -d {home}/.local/state/workers-plain/alpha-* {areas}/alpha-*/plain/session").split()
    print("V8 ordinary sessions:", sessions)
    assert len(sessions) == 4, sessions

with subtest("B3: a project that contains the workers' folders is refused; a folder inside it starts"):
    # B3: the same for the folder a session is started in, and for a repository found above it; a folder inside still starts
    out = refused("", "it contains the workers' folders; start worker-shell in a folder inside it", project="~/scratch")
    print("B3:", out)
    assert machine.succeed(start("", f'pwd; ls {areas} | wc -l', project="~/scratch/own")).split() == [f"{home}/scratch/own", "1"]
    machine.succeed(asUser("git init -q ~/scratch"))
    refused("", "it contains the workers' folders", project="~/scratch/own")
    machine.succeed(asUser("rm -rf ~/scratch/.git"))

with subtest("C4: two workers whose names would run together into one unit name run at once"):
    # C4 (E9 of the deep review): project x-y with branch z, and project x with branch y-z, both with a worker n, run at once
    machine.succeed(f"({start('--branch z --name n', gate('c4-go'), project='~/x-y')}) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(asUser("systemctl --user is-active --quiet worker:x-y:z:n.scope"), timeout=20 * pace)
    assert machine.succeed(start("--branch y-z --name n", "echo second-ran", project="~/x")).strip() == "second-ran"
    machine.succeed(asUser("systemctl --user is-active worker:x-y:z:n.scope"))
    openGate("x-y/z/n", "c4-go")
    sandboxEnded("x-y/z/n")

with subtest("An ordinary session's records are kept within a size"):
    machine.succeed(start("", "for i in 1 2 3 4 5 6 7 8; do queue run -- true; done", project="~/group/project", launcher="worker-shell-small"))
    sizes = machine.succeed(f"wc -c {home}/.local/state/workers-plain/project-*/records.jsonl*")
    print("ordinary records:", sizes)
    assert "records.jsonl.1" in sizes and all(int(line.split()[0]) < 1200 for line in sizes.strip().splitlines()[:-1]), sizes

with subtest("A limit can be changed until the next restart, as the documentation says"):
    machine.succeed(start("--branch b1 --name i1", "true"))
    out = machine.succeed(asUser("systemctl --user set-property --runtime workers-agents.slice MemoryMax=900M CPUQuota=250% && systemctl --user show -p MemoryMax -p CPUQuotaPerSecUSec workers-agents.slice"))
    print("limits changed:", out)
    assert "MemoryMax=943718400" in out and "CPUQuotaPerSecUSec=2.500000s" in out, out

with subtest("V9 and V21: a worker gets its role's file and its own task file, checked and copied"):
    task = lambda name, role, body="Do the thing.", branch="b1": f"mkdir -p ~/workers/alpha/instructions/{branch} && printf 'branch: {branch}\\nname: {name}\\nrole: {role}\\n\\n{body}\\n' > ~/workers/alpha/instructions/{branch}/{name}.md"
    # Without a task file a worker that takes instructions does not start
    out = refused("--branch b1 --name i1", "there is no file", launcher="worker-args")
    assert "the worker does not start without its task file" in out, out
    # The manager writes the task files; it has none itself
    machine.succeed(start("--role manager", task("i1", "implementer") + " && " + task("r1", "reviewer") + " && " + task("d1", "deep-reviewer")))
    expected = {
        "--branch b1 --name i1": "implementer",
        "--role reviewer --branch b1 --name r1 --of i1": "reviewer",
        "--role deep-reviewer --branch b1 --name d1": "deep-reviewer",
    }
    for options, role in expected.items():
        out = machine.succeed(start(options, launcher="worker-args"))
        print(f"V21 {role}:", out)
        lines = [line for line in out.splitlines() if line.startswith("argument:")]
        # A reviewer also gets the project's rules, since it does not start in a copy of the project
        files = ["/run/project-rules.md", "/run/task.md"] if role == "reviewer" else ["/run/task.md"]
        assert lines[0::2] == ["argument: --instructions"] * (1 + len(files)) and lines[3::2] == [f"argument: {file}" for file in files], out
        assert f"worker-role-{role}.md" in lines[1] and f"Your role in this session is {role}." in out and f"    role: {role}" in out and "    Do the thing." in out, out
        if role == "implementer":
            assert "Finish the implementation and validation, then write a clear handoff and stop. Do not wait for a reviewer in the implementation session." in out, out
    out = machine.succeed(start("--role manager", launcher="worker-args"))
    print("V21 manager:", out)
    assert [line for line in out.splitlines() if line.startswith("argument:")][0] == "argument: --instructions" and out.count("argument:") == 2 and "role in this session is manager" in out, out
    assert "To read any worker’s reports or records, including a worker started after this manager, use `worker-read <branch>/<name> <reports|records> [<path>]`; do not rely on the worker being visible as a direct path." in out, out
    assert "After each implementer reports completion, start a separate reviewer or deep-reviewer worker. Do not ask the implementer to wait for or perform its own review." in out, out
    assert "Manager advice must be written to `reports/advice/<branch>/<worker>.md` with the exact worker, form-sha256, task-sha256, and tests-commit headers; use `worker-read` for the form, the manager-owned task file for the task hash, and the project branch commit that supplies the tests." in out, out
    # A stand-in that takes no instructions gets none
    assert machine.succeed(start("--branch b1 --name i1", 'echo "arguments=$#"')).strip() == "arguments=0"

    # A header for another worker, branch or role
    for name, header in [("w1", ("b1", "other", "implementer")), ("w2", ("b2", "w2", "implementer")), ("w3", ("b1", "w3", "reviewer"))]:
        machine.succeed(start("--role manager", f"printf 'branch: {header[0]}\\nname: {header[1]}\\nrole: {header[2]}\\n\\nText.\\n' > ~/workers/alpha/instructions/b1/{name}.md"))
        refused(f"--branch b1 --name {name}", "does not start with the lines", launcher="worker-args")
    # A link to a file outside, planted by a manager; and a file that is too large
    machine.succeed(start("--role manager", f"ln -s {home}/.ssh/id_test ~/workers/alpha/instructions/b1/w4.md && {{ printf 'branch: b1\\nname: w5\\nrole: implementer\\n'; head -c 300000 /dev/zero | tr '\\0' x; }} > ~/workers/alpha/instructions/b1/w5.md"))
    out = refused("--branch b1 --name w4", "reached without a link", launcher="worker-args")
    assert "secret" not in out, out
    refused("--branch b1 --name w5", "is larger than 262144 bytes", launcher="worker-args")
    # H3: the file is opened once, without following a link and without waiting. A pipe in its place, and a link on the way to it
    machine.succeed(start("--role manager", "mkfifo ~/workers/alpha/instructions/b1/w6.md; mkdir ~/workers/alpha/instructions/real && printf 'branch: b2\\nname: w7\\nrole: implementer\\n' > ~/workers/alpha/instructions/real/w7.md && ln -s real ~/workers/alpha/instructions/b2"))
    out = machine.fail("timeout 10 " + start("--branch b1 --name w6", launcher="worker-args") + " 2>&1")
    assert "is not a regular file" in out, out
    refused("--branch b2 --name w7", "reached without a link", launcher="worker-args")
    # The file exchanged again and again while workers start: every start gets this worker's task or is refused; none hangs, none gets the key
    swap = (
        "cd ~/workers/alpha/instructions/b1; printf 'branch: b1\\nname: w8\\nrole: implementer\\n\\nThe real task.\\n' > good;"
        " touch $WORKER_SCRATCH/h3-runs; until [ -e $WORKER_SCRATCH/h3-stop ]; do cp good w8.md; rm -f w8.md; mkfifo w8.md; rm -f w8.md; ln -s " + home + "/.ssh/id_test w8.md; rm -f w8.md; done"
    )
    # (the manager exchanges the file from before the first start until after the last one)
    machine.succeed(f"({start('--role manager', swap)}) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/manager/h3-runs", timeout=30 * pace)
    outcomes = []
    for _ in range(8):
        status, out = machine.execute(f"timeout {10 * pace} " + start("--branch b1 --name w8", launcher="worker-args") + " 2>&1")
        assert status != 124 and "secret" not in out and (("The real task." in out) == (status == 0)), (status, out)
        outcomes.append(status)
    print("H3 starts while the file is exchanged:", outcomes)
    openGate("alpha/manager/manager", "h3-stop")
    sandboxEnded("alpha/manager/manager")
    machine.succeed(start("--role manager", "rm -f ~/workers/alpha/instructions/b1/w6.md ~/workers/alpha/instructions/b1/good"))
    # A refused start leaves nothing behind: no folder, no scratch area
    listed = machine.succeed(f"ls {folders}/alpha/b1 {areas}/alpha/b1").split()
    assert "w1" not in listed and "w6" not in listed, listed
    # Only the manager reaches the task files
    out = machine.succeed(start("--branch b1 --name i1", 'ls ~/workers/alpha/instructions; echo "list=$?"; cat /run/task.md; echo "task=$?"') + " 2>&1")
    assert "list=2" in out and "task=1" in out, out

with subtest("V9 and C1: neither a change to the task file nor a second start reaches the worker that runs"):
    # A change to the task file does not reach the worker that runs
    # (the worker shows its task, waits at a gate, and shows it again)
    machine.succeed(f"({start('--branch b1 --name i1', launcher='worker-args', prefix=f'WAIT_FOR={areas}/alpha/b1/i1/v9-go ')}) > /tmp/running 2>&1 &")
    machine.wait_until_succeeds("grep -q 'Do the thing.' /tmp/running", timeout=30 * pace)
    machine.succeed(start("--role manager", task("i1", "implementer", "CHANGED")))
    # C1 (R1 of the deep review): a second start of the worker that runs is refused before anything is written, so the changed
    # task does not reach the one that runs. The copy is the same file as before
    copy = "/run/user/1000/workers/worker:alpha:b1:i1.task"
    before = machine.succeed(f"stat -c %i {copy}; cat {copy}")
    refused("--branch b1 --name i1", "is already running", launcher="worker-args")
    assert machine.succeed(f"stat -c %i {copy}; cat {copy}") == before and "CHANGED" not in before, before
    openGate("alpha/b1/i1", "v9-go")
    machine.wait_until_succeeds("grep -q 'the task afterwards' /tmp/running", timeout=30 * pace)
    sandboxEnded("alpha/b1/i1")
    out = machine.succeed("cat /tmp/running")
    print("V9 a running worker's task:", out)
    assert out.count("Do the thing.") == 2 and "CHANGED" not in out, out
    # C5 of the deep review: when the sandbox has ended, its runtime state is gone: the copy of the task, and the folder with
    # the view and the socket. So the next start writes a new copy, and never into an old one
    gone = f"! test -e {copy} && ! test -e /run/user/1000/workers/worker:alpha:b1:i1"
    machine.wait_until_succeeds(gone, timeout=10 * pace)
    assert "CHANGED" in machine.succeed(start("--branch b1 --name i1", launcher="worker-args"))
    machine.wait_until_succeeds(gone, timeout=10 * pace)
    # Two starts of one name at the same moment: one runs, the other is refused, whichever comes first
    machine.succeed(f"({start('--branch b1 --name i1', f'sleep {3 * pace}; echo first-done')}) > /tmp/first 2>&1 & ({start('--branch b1 --name i1', f'sleep {3 * pace}; echo second-done')}) > /tmp/second 2>&1 & wait")
    out = machine.succeed("cat /tmp/first /tmp/second")
    print("C1, two starts at once:", out)
    assert out.count("-done") == 1 and ("is already running" in out or "is under way" in out), out

with subtest("V14 and V15: what each role reads and writes"):
    target, area = f"{folders}/alpha/b1/i1", f"{areas}/alpha/b1/i1"
    machine.succeed(
        # A reviewer sees what an implementer committed, and nothing else of its copy
        start("--branch b1 --name i1", "printf 'echo result-of-the-reviewed-code\\n' > run.sh; echo draft > not-committed; git add run.sh file-of-i1 && git -c user.name=t -c user.email=t@t commit -q -m work"),
        start("--branch b1 --name i2", "echo of-i2 > file-of-i2; echo report-of-i2 > ../reports/r"),
        start("--role reviewer --branch b1 --name r1 --of i1", "echo review-by-r1 > $HOME/workers/alpha/b1/r1/reports/review"),
        start("--role reviewer --branch b1 --name r2 --of i2", "echo review-by-r2 > $HOME/workers/alpha/b1/r2/reports/review"),
        start("--branch b2 --name j1", "echo of-j1 > file-of-j1"),
    )
    clean = f"{folders}/alpha/b1/r1/repo"
    reviewer = (
        f'pwd; cat ../repo/file-of-i1 {target}/reports/r {area}/d; echo "read=$?"; git -C ../repo log --format=%s -1; git -C ../repo diff --stat origin/b1 HEAD | tail -n 1;'
        ' git --git-dir ~/alpha/.git log --format=%s -1; echo "base=$?";'
        f' ls ../repo/not-committed {target}/repo 2>&1; echo "draft-and-the-implementers-copy=$?";'
        f' for p in {clean} {clean}/.git {target}/reports {target}/records {area} ~/alpha/.git; do if touch $p/x 2>/dev/null; then echo "$p writable"; else echo "$p protected"; fi; done;'
        " bash ../repo/run.sh > $WORKER_SCRATCH/direct; (cd ../repo && queue run -- bash run.sh) > $WORKER_SCRATCH/queued; cat $WORKER_SCRATCH/direct $WORKER_SCRATCH/queued;"
        ' echo more >> review; echo "own-report=$?";'
        f' ls ~/workers/alpha/b1; ls {target}; ls {target}/sessions; echo "sessions=$?"; ls ~/alpha; echo "project=$?"'
    )
    out = machine.succeed(start("--role reviewer --branch b1 --name r1 --of i1", reviewer) + " 2>&1")
    print("V14 reviewer:", out)
    # It starts in its own folder; the implementer's committed work is in its clean copy, with the project's branch to compare with
    assert out.splitlines()[0] == f"{folders}/alpha/b1/r1/reports" and "of-i1\nreport-of-i1\ndata-of-i1\nread=0\nwork\n 2 files changed, 2 insertions(+)\nbase\nbase=0" in out, out
    # Neither the implementer's uncommitted file nor its copy is there
    assert "draft-and-the-implementers-copy=2" in out and "draft" not in out.replace("draft-and", ""), out
    for path in [clean, f"{clean}/.git", f"{target}/reports", f"{target}/records", area, f"{home}/alpha/.git"]:
        assert f"{path} protected" in out, out
    assert out.count("result-of-the-reviewed-code") == 2 and "own-report=0" in out, out
    # Of its branch it sees the implementer it reviews and itself: no other implementer, no other reviewer, no sessions, no project files
    assert "\ni1\nr1\nrecords\nreports\n" in out and "sessions=2" in out and "i2" not in out and "r2" not in out, out
    assert out.rstrip().endswith("project=0") and "file\n" not in out.split("sessions=2")[1], out

    # H2: a reviewer takes the project's rules from the project, never from the copy it reviews
    machine.succeed(start("--branch b1 --name i1", "echo 'rules by the implementer' > AGENTS.md; echo 'override by the implementer' > AGENTS.override.md"))
    out = machine.succeed(start("--role reviewer --branch b1 --name r1 --of i1", launcher="worker-args"))
    print("H2 reviewer:", out)
    assert f"folder: {folders}/alpha/b1/r1/reports" in out and "AGENTS" not in out.split("argument:")[0], out
    assert "argument: /run/project-rules.md\n    rules of the project" in out and "by the implementer" not in out, out
    assert [line for line in out.splitlines() if line.startswith("argument: /")][1:] == ["argument: /run/project-rules.md", "argument: /run/task.md"], out
    # Control: the implementer itself starts in its copy, where both files are
    out = machine.succeed(start("--branch b1 --name i1", launcher="worker-args"))
    assert f"folder: {target}/repo" in out and "in the folder: AGENTS.md" in out and "in the folder: AGENTS.override.md" in out and "project-rules" not in out, out

    own = f"{folders}/alpha/b1/d1/repo"
    deep = (
        f'pwd; cat file {folders}/alpha/b1/i2/reports/r {area}/d; echo "read=$?"; git -C {own} show reviewed/i1/worker/b1/i1:file-of-i1; git -C {own} log --format=%s -1 reviewed/i2/worker/b1/i2;'
        f' ls {own}; ls {target}/repo {folders}/alpha/b1/i2/repo 2>&1 | grep -c "No such file";'
        f' for p in . {own} {target}/reports {area} {folders}/alpha/b1/i2/reports; do if touch $p/x 2>/dev/null; then echo "$p writable"; else echo "$p protected"; fi; done;'
        ' echo deep > ~/workers/alpha/b1/d1/reports/deep; echo "own-report=$?"; ls ~/workers/alpha ~/workers/alpha/b1'
    )
    out = machine.succeed(start("--role deep-reviewer --branch b1 --name d1", deep) + " 2>&1")
    print("V14 deep reviewer:", out)
    # It starts in the project; its clean copy shows the project's branch and holds what each implementer of the branch committed
    assert out.splitlines()[0] == f"{home}/alpha" and "content\nreport-of-i2\ndata-of-i1\nread=0\nof-i1\nbase\nAGENTS.md\nfile\n2\n" in out and "own-report=0" in out, out
    assert out.count("protected") == 5 and "writable" not in out, out
    # The implementers of its branch and itself: no reviewer, no other branch
    # (w8 is the implementer of the exchange test above, if one of its starts got through)
    seen = set(out.rstrip().split(f"{folders}/alpha/b1:\n")[1].split())
    assert {"d1", "i1", "i2"} <= seen <= {"d1", "i1", "i2", "w8"} and "b2" not in out, out

    # V15: a worker does not see another worker's sessions; the manager reads every worker, reviewers included
    out = machine.succeed(start("--branch b1 --name i2", f'ls ~/.pi/agent/sessions | wc -l; ls {target}/sessions; echo "other-sessions=$?"') + " 2>&1")
    assert out.split()[0] == "0" and "other-sessions=2" in out, out
    out = machine.succeed(start("--role manager", f"cat {folders}/alpha/b1/r1/reports/review {folders}/alpha/b1/r2/reports/review {folders}/alpha/b2/j1/repo/file-of-j1 {target}/sessions/s"))
    print("V15 manager:", out)
    assert out.split() == ["review-by-r1", "more", "review-by-r2", "of-j1", "session"], out

with subtest("B1: one live manager reads every managed artefact of a later worker"):
    machine.succeed(start("--branch b1 --name i1", "queue run -- true"))
    out = machine.succeed(start("--role manager", "worker-read b1/i1 reports r; worker-read b1/i1 records runs.jsonl | grep -m1 '\"name\": \"i1\"'; worker-read --sha256 b1/i1 reports r; worker-read b1/i1 reports"))
    assert out.splitlines()[0] == "report-of-i1" and '"name": "i1"' in out and hashlib.sha256(b"report-of-i1\n").hexdigest() in out and '"r"' in out, out
    manager = task("late-reader", "implementer", branch="b2") + ";touch $WORKER_SCRATCH/ready;" + gate("go") + ";worker-read --workers;worker-read b2/late-reader folder;worker-read b2/late-reader repo untracked;worker-read b2/late-reader reports head;worker-read b2/late-reader records runs.jsonl|grep -m1 late-reader;worker-read b2/late-reader diff file;worker-read b2/late-reader refs;for r in sessions scratch;do worker-read b2/late-reader $r big>$WORKER_SCRATCH/a 2>$WORKER_SCRATCH/e;worker-read --offset 262144 b2/late-reader $r big>$WORKER_SCRATCH/b;echo $r=$(wc -c<$WORKER_SCRATCH/a),$(wc -c<$WORKER_SCRATCH/b);cat $WORKER_SCRATCH/e;done;worker-read b2/late-reader diff large>$WORKER_SCRATCH/a 2>$WORKER_SCRATCH/e;echo limit=$?,$(wc -c<$WORKER_SCRATCH/a);cat $WORKER_SCRATCH/e"
    machine.succeed(f"rm -f /tmp/reader-*-ran;({start('--role manager --name reader-manager', manager)})>/tmp/reader 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/reader-manager/ready", timeout=30 * pace)
    later = "s=$(command -v bash);printf '#!%s\\ntouch /tmp/reader-external-ran\\necho HOSTILE-EXTERNAL\\n' \"$s\">external;printf '#!%s\\ntouch /tmp/reader-textconv-ran\\necho HOSTILE-TEXTCONV\\n' \"$s\">textconv;chmod +x external textconv;git config diff.external $PWD/external;git config diff.evil.textconv $PWD/textconv;echo 'file diff=evil'>.gitattributes;echo base>large;git add large;git -c user.name=t -c user.email=t@t commit -q -m reader -- large;git tag reader-tag;git rev-parse HEAD>../reports/head;echo late>>file;git add file;echo later>>file;echo uncommitted>untracked;head -c 300000 /dev/zero|tr '\\0' L>large;head -c 300000 /dev/zero|tr '\\0' S>~/.pi/agent/sessions/big;head -c 300000 /dev/zero|tr '\\0' G>$WORKER_SCRATCH/big;queue run -- true"
    machine.succeed(start("--branch b2 --name late-reader", later))
    openGate("alpha/manager/reader-manager", "go")
    sandboxEnded("alpha/manager/reader-manager")
    out = machine.succeed("cat /tmp/reader")
    print("B1 reader:", out)
    head = machine.succeed(f"cat {folders}/alpha/b2/late-reader/reports/head").strip()
    assert '"b2/late-reader"' in out and all(f'"{x}"' in out for x in ["records", "repo", "reports", "sessions"]) and "uncommitted" in out and '"name": "late-reader"' in out, out
    assert "index d95f3ad..22fd997" in out and "+late\n+later" in out and f"{head} refs/heads/worker/b2/late-reader" in out and f"{head} refs/tags/reader-tag" in out, out
    assert "sessions=262144,37856" in out and "scratch=262144,37856" in out and "limit=2,0" in out and "diff is larger than 262144 bytes" in out, out
    assert "HOSTILE-" not in out and machine.succeed("test ! -e /tmp/reader-external-ran -a ! -e /tmp/reader-textconv-ran;echo safe").strip() == "safe", out

with subtest("A3: nothing of the reviewed work can write a reviewer's report"):
    # R2 of the deep review: the implementer sets a program in its copy's git settings that writes into every report it can reach,
    # and commits a test that does the same
    writer = lambda word: f"for r in ../reports {home}/workers/*/*/*/reports; do echo {word} >> $r/review; done"
    plant = (
        f"printf '#!/bin/sh\\n%s 2>/dev/null\\n' {shlex.quote(writer('APPROVED-by-the-settings-of-the-reviewed-copy'))} > settings.sh; chmod +x settings.sh;"
        f" printf '%s\\necho the-test-ran\\n' {shlex.quote(writer('PASSED-says-the-reviewed-test'))} > test.sh;"
        " git add settings.sh test.sh && git -c user.name=t -c user.email=t@t commit -q -m 'a test'; git config core.fsmonitor \"$PWD/settings.sh\"; git status --short > /dev/null; cat ../reports/review"
    )
    # Control: the planted program works. In the implementer's own sandbox, git runs it and it writes the implementer's own report
    out = machine.succeed(start("--branch b1 --name i1", plant) + " 2>&1")
    assert "APPROVED-by-the-settings-of-the-reviewed-copy" in out, out
    report = f"{folders}/alpha/b1/r1/reports/review"
    # The reviewer's way of working: git in its clean copy, and the reviewed code through the queue
    look = (
        "echo my-own-review > review; git -C ../repo status --short; git -C ../repo log --format=%s -1; git -C ../repo diff --stat origin/b1 HEAD | tail -n 1;"
        f' git -C {target}/repo status --short 2>&1 | cut -c1-60; (cd ../repo && queue run -- bash test.sh 2>&1); echo "job=$?"; cat review'
    )
    out = machine.succeed(start("--role reviewer --branch b1 --name r1 --of i1", look) + " 2>&1")
    print("A3 reviewer:", out)
    lines = out.strip().splitlines()
    assert lines[0] == "a test" and "4 files changed" in lines[1] and "cannot change to" in lines[2] and "the-test-ran" in lines and "job=0" in lines, out
    # The job could not write the report: the reviewer's and the host's view of it agree
    assert out.count("Read-only file system") >= 1 and lines[-1] == "my-own-review" and machine.succeed(f"cat {report}").strip() == "my-own-review", out
    # The documented way for a test that writes into its own tree: a copy of the tree in the scratch area, inside a job
    tree = "queue run -- bash -c 'mkdir -p \"$WORKER_SCRATCH/tree\" && git -C ../repo archive HEAD | tar -x -C \"$WORKER_SCRATCH/tree\" && cd \"$WORKER_SCRATCH/tree\" && echo written > into-the-tree && bash test.sh 2>&1 | tail -n 1'; cat review"
    assert machine.succeed(start("--role reviewer --branch b1 --name r1 --of i1", tree)).split() == ["the-test-ran", "my-own-review"]
    # The deep reviewer: git in its clean copy, and an implementer's code taken from there and run through the queue
    own = f"{folders}/alpha/b1/d1/repo"
    look = (
        f"echo deep-review > ~/workers/alpha/b1/d1/reports/review; git -C {own} status --short; git -C {own} log --format=%s -1 reviewed/i1/worker/b1/i1;"
        f' git -C {target}/repo status --short 2>&1 | cut -c1-60; queue run -- bash -c "git -C {own} show reviewed/i1/worker/b1/i1:test.sh | bash 2>&1"; echo "job=$?"; cat ~/workers/alpha/b1/d1/reports/review'
    )
    out = machine.succeed(start("--role deep-reviewer --branch b1 --name d1", look) + " 2>&1")
    print("A3 deep reviewer:", out)
    lines = out.strip().splitlines()
    assert lines[0] == "a test" and "cannot change to" in lines[1] and "the-test-ran" in lines and "job=0" in lines and lines[-1] == "deep-review", out
    assert machine.succeed(f"cat {folders}/alpha/b1/d1/reports/review").strip() == "deep-review"
    # Control, and the stated limit: the same test run directly in the reviewer's own sandbox, not through the queue, does write the report
    out = machine.succeed(start("--role reviewer --branch b1 --name r1 --of i1", "bash ../repo/test.sh > /dev/null 2>&1; cat review"))
    assert out.split() == ["my-own-review", "PASSED-says-the-reviewed-test", "PASSED-says-the-reviewed-test"], out
    # A reviewer's copy follows the implementer's commits at its next start, and a reviewer is removed like any worker
    machine.succeed(start("--branch b1 --name i1", "git config --unset core.fsmonitor; echo later > later && git add later && git -c user.name=t -c user.email=t@t commit -q -m later"))
    assert machine.succeed(start("--role reviewer --branch b1 --name r1 --of i1", "cat ../repo/later; git -C ../repo log --format=%s -1")).split() == ["later", "later"]
    # An implementer whose branch is gone from its copy cannot be reviewed, and the reviewer says why
    machine.succeed(start("--branch b1 --name i2", "git checkout -q -b elsewhere && git branch -D worker/b1/i2 > /dev/null"))
    out = refused("--role reviewer --branch b1 --name r2 --of i2", "could not be made")
    assert "the copy of i2 has no branch worker/b1/i2, so there is nothing to review" in out, out

with subtest("Finding 2: a manager cannot show another worker a folder outside its view"):
    machine.succeed(asUser("mkdir -p ~/outside && echo outside-content > ~/outside/marker"))
    shown = f"{folders}/alpha/manager/manager/repo/.git"
    look = f"cat {shown}/marker 2>&1 | head -n 1; ls {home}/outside 2>&1 | head -n 1"
    # Control: an implementer sees the manager's history, and not the folder outside
    out = machine.succeed(start("--branch b1 --name i1", f"ls {shown}/HEAD; {look}") + " 2>&1")
    assert f"{shown}/HEAD" in out and "outside-content" not in out, out
    # R2 of the review: the manager exchanges the history folder of its copy for a link, again and again, while an implementer starts twelve times
    # (from before the first start until after the last one)
    swap = f"touch $WORKER_SCRATCH/r2-runs; until [ -e $WORKER_SCRATCH/r2-stop ]; do mv .git .git-kept; ln -s {home}/outside .git; sleep 0.05; rm .git; mv .git-kept .git; sleep 0.05; done"
    machine.succeed(f"({start('--role manager', swap)}) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/manager/r2-runs", timeout=30 * pace)
    outcomes = []
    for attempt in range(12):
        status, out = machine.execute(start("--branch b1 --name i1", look + f"; readlink {shown} 2>/dev/null; true") + " 2>&1")
        outcomes.append("shown" if "outside-content" in out else ("the link, leading nowhere" if f"{home}/outside" in out.splitlines()[-1:] else ("started" if status == 0 else "refused")))
    print("R2:", outcomes)
    openGate("alpha/manager/manager", "r2-stop")
    sandboxEnded("alpha/manager/manager")
    assert "shown" not in outcomes and "refused" not in outcomes, outcomes
    # The exchange did happen during the starts: at least one start saw the link itself, and could not follow it
    assert "the link, leading nowhere" in outcomes, outcomes

with subtest("For the proposal on bringing in an existing project: --allow-ro of the project gives a manager its files as they lie there, read-only"):
    machine.succeed(asUser("echo work-in-progress > ~/alpha/not-committed-by-the-user"))
    look = 'cat ~/alpha/not-committed-by-the-user 2>&1 | tail -c 26; git -C ~/alpha status --short 2>&1 | tail -n 1; touch ~/alpha/x 2>/dev/null; echo "write=$?"'
    # Control: without the option a manager sees the project's history and none of its files
    out = machine.succeed(start("--role manager", look))
    assert "work-in-progress" not in out and "write=1" in out, out
    out = machine.succeed(start("--allow-ro ~/alpha --role manager", look))
    print("a manager with --allow-ro of the project:", out)
    assert out.split() == ["work-in-progress", "??", "not-committed-by-the-user", "write=1"], out
    machine.succeed(asUser("rm ~/alpha/not-committed-by-the-user"))

with subtest("Point 5 of the review: the real pi in every role, and tools of a development shell, with the sandbox's top folder read-only"):
    # pi has a key that is no key, and this machine has no way out: pi starts, reads its instructions, and fails at its first
    # request, which names the provider's host. A start that needed to write where it cannot would end before that
    machine.fail("timeout 5 bash -c 'echo > /dev/tcp/1.1.1.1/443'")
    machine.succeed(asUser("mkdir -p ~/.pi/agent/login && printf '{\"openai\": {\"type\": \"api_key\", \"key\": \"not-a-key\"}}' > ~/.pi/agent/login/auth.json"))
    machine.succeed(start("--role manager", task("i1", "implementer") + " && " + task("r1", "reviewer") + " && " + task("d1", "deep-reviewer")))
    asked = "--provider openai --model gpt-4o --no-session -p hi"
    for options in ["--branch b1 --name i1", "--role reviewer --branch b1 --name r1 --of i1", "--role deep-reviewer --branch b1 --name d1", "--role manager", ""]:
        status, out = machine.execute("timeout 150 " + start(f"{options} {asked}".strip(), launcher="worker-pi") + " 2>&1")
        print(f"pi with '{options}': status {status}:", out.strip()[-300:])
        assert "api.openai.com" in out and "Read-only file system" not in out and "EROFS" not in out and status != 124, f"{options}: {out}"
    # The tools, by the agent and inside a job
    tools = r"""
python3 -c "import tempfile, multiprocessing.shared_memory as memory; folder = tempfile.mkdtemp(); block = memory.SharedMemory(create=True, size=1 << 20); block.close(); block.unlink(); print('python-ok')"
uv venv -q "$WORKER_SCRATCH/trial-venv-$1" && "$WORKER_SCRATCH/trial-venv-$1/bin/python" -c "print('uv-ok')"
cd "$(mktemp -d)" && printf '#include <stdio.h>\nint main(void) { puts("c-ok"); return 0; }\n' > trial.c && gcc trial.c -o trial && ./trial
printf 'all:\n\t@echo make-ok\n' > Makefile && make
git init -q . && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m trial && echo git-ok
mkdir /var/tmp 2> /dev/null; echo "var-tmp=$?"
"""
    machine.succeed("cat > /tmp/tools.sh <<'END'\n" + tools + "\nEND", f"install -o {user} -m 755 /tmp/tools.sh {areas}/alpha/b1/i1/tools.sh")
    for label, command in [("the agent", "bash $WORKER_SCRATCH/tools.sh agent"), ("a job", "queue run -- bash $WORKER_SCRATCH/tools.sh job")]:
        out = machine.succeed(start("--branch b1 --name i1", command) + " 2>&1")
        print(f"tools, {label}:", out)
        assert out.split() == ["python-ok", "uv-ok", "c-ok", "make-ok", "git-ok", "var-tmp=1"], f"{label}: {out}"
    # An experiment, printed and not judged: two processes of Open MPI, which keeps shared memory in /dev/shm or /tmp
    status, out = machine.execute("timeout 60 " + start("--branch b1 --name i1", "mpirun -np 2 --oversubscribe echo mpi-ran") + " 2>&1")
    print(f"EXPERIMENT mpirun: status {status}:", out.strip()[-600:])

with subtest("B1: the approval acknowledgement has no writable runtime-directory path"):
    machine.succeed(start("--role manager", task("ack-probe", "implementer")))
    machine.succeed(f"{start('--branch b1 --name ack-probe', launcher='worker-control-probe')} > /tmp/control-probe-launch 2>&1 & echo $! > /tmp/control-probe-pid")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/ack-probe/control-probe-ready", timeout=30 * pace)
    result = machine.succeed(f"cat {areas}/alpha/b1/ack-probe/control-probe-result")
    print("B1 control probe:", result)
    assert result.splitlines() == ["started=refused", "mode=refused", "create=refused"], result
    control = "/run/user/1000/workers/worker:alpha:b1:ack-probe.control"
    assert machine.execute(f"test \"$(cat '{control}/mode')\" = supported && test ! -e '{control}/started' && test ! -e '{control}/created'")[0] == 0, machine.succeed(f"find '{control}' -maxdepth 1 -printf '%f %y %s\\n'")
    machine.succeed(f"touch {areas}/alpha/b1/ack-probe/control-probe-stop")
    machine.wait_until_succeeds("! kill -0 $(cat /tmp/control-probe-pid) 2>/dev/null", timeout=10 * pace)
    machine.succeed(f"test ! -e '{control}'")

    # Repeated, oversized and idle acknowledgement connections neither delay child exit nor change the recovery decision
    acknowledgementAttack = r'''import os
import socket
import sys
import time

path, nonce, mode, pidFile = sys.argv[1:]
deadline = time.monotonic() + 1
while not os.path.exists(path) and time.monotonic() < deadline:
    time.sleep(0.01)

idle = []
def record(message):
    with open(pidFile + ".events", "a") as file:
        file.write(message + "\n")

def connect(payload=None, keep=False):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(0.2)
    try:
        connection.connect(path)
        if payload is not None:
            connection.sendall(payload)
        record(f"connected bytes={len(payload) if payload is not None else 0} keep={keep}")
        if keep:
            idle.append(connection)
            return
    except OSError as error:
        record(f"refused {error!r}")
    connection.close()

connect(b"wrong\n")
if mode == "valid":
    connect((nonce + "\n").encode())
    connect((nonce + "\n").encode())
connect(b"x" * 8192)
time.sleep(0.3)
for _ in range(12):
    connect(keep=True)

child = os.fork()
if child == 0:
    with open(pidFile, "w") as file:
        file.write(f"{os.getpid()}\n")
    null = os.open(os.devnull, os.O_RDWR)
    for descriptor in (0, 1, 2):
        os.dup2(null, descriptor)
    os.close(null)
    time.sleep(10)
    os._exit(0)
os._exit(7)
'''
    machine.succeed("cat > /tmp/acknowledgement-attack.py <<'PY'\n" + acknowledgementAttack + "PY")
    for mode in ("invalid", "valid"):
        unit = f"worker:alpha:b1:ack-{mode}"
        nonce = f"0123456789abcdef0123456789abc{mode[0]}"
        control = f"/run/user/1000/workers/{unit}.control"
        lock = f"/run/user/1000/workers/{unit}.lock"
        pidFile = f"/tmp/ack-{mode}-idle-pid"
        machine.succeed(f"install -d -o {user} -g users -m 700 '{control}'", f"rm -f '{lock}' '{pidFile}' '{pidFile}.events'")
        command = f"timeout 3 env WORKER_INTERNAL_RESTART={shlex.quote(unit)} WORKER_INTERNAL_RESTART_NONCE={shlex.quote(nonce)} worker-supervise-test {shlex.quote(control)} {shlex.quote(lock)} {shlex.quote(unit)} /run/current-system/sw/bin/false {home}/alpha b1 ack-{mode} 0 -- python3 /tmp/acknowledgement-attack.py {shlex.quote(control + '/started')} {shlex.quote(nonce)} {mode} {shlex.quote(pidFile)}"
        status, output = machine.execute(asUser(command) + " 2>&1")
        events = machine.succeed(f"cat '{pidFile}.events'")
        print(f"B1 supervisor {mode}:", status, output, events)
        assert status == 7, (status, output, events)
        assert ("automatic continuation failed" in output) == (mode == "invalid"), output
        assert machine.execute(f"test ! -e '{control}'")[0] == 0, machine.succeed(f"find '{control}' -maxdepth 1 -printf '%f %y %s\\n' 2>/dev/null || true")
        machine.succeed(f"for _ in $(seq 1 20); do [ -s '{pidFile}' ] && break; sleep 0.05; done; if [ -s '{pidFile}' ]; then kill $(cat '{pidFile}') 2>/dev/null || true; fi; rm -f '{pidFile}' '{pidFile}.events' '{lock}'")

with subtest("Round 6 item 6: approval gracefully continues an open pi chat in a writable sandbox"):
    machine.succeed(start("--role manager", task("restart1", "implementer") + " && " + task("restart-fd-path", "implementer") + " && " + task("restart-fd-lock", "implementer")))
    forgedPath = machine.fail(asUser("bash -c 'exec 9</dev/null; cd ~/alpha; WORKER_INTERNAL_RESTART=worker:alpha:b1:restart-fd-path worker-args --branch b1 --name restart-fd-path'") + " 2>&1")
    assert "inherited descriptor 9 does not name the worker start lock" in forgedPath, forgedPath
    forgedLock = machine.fail(asUser("bash -c 'exec 9>/run/user/1000/workers/worker:alpha:b1:restart-fd-lock.lock; cd ~/alpha; WORKER_INTERNAL_RESTART=worker:alpha:b1:restart-fd-lock worker-args --branch b1 --name restart-fd-lock'") + " 2>&1")
    assert "inherited descriptor 9 does not hold the worker start lock" in forgedLock, forgedLock
    startScript = f'''#!/bin/sh
export HOME={home} USER={user} XDG_RUNTIME_DIR=/run/user/1000 TERM=xterm-256color
export PATH=/run/wrappers/bin:/run/current-system/sw/bin
cd {home}/alpha
exec worker-pi-restart --branch b1 --name restart1
'''
    expectScript = rf'''set timeout {realPiTimeout}
log_file -noappend /tmp/restart1.log
spawn /tmp/start-restart1
expect "(worker-test) deterministic"
send "first chat message\r"
expect "WORKER-TEST-ANSWER"
send "/detached-job\r"
expect "DETACHED-JOB-SUBMITTED"
send "draft survives restart"
exec touch /tmp/restart1-ready
expect "Approval opened the copy; this answer and chat will be saved, then pi will continue automatically."
expect "restored your unsubmitted"
expect eof
'''
    machine.succeed("cat > /tmp/start-restart1 <<'END'\n" + startScript + "END", "cat > /tmp/restart1.exp <<'END'\n" + expectScript + "END", f"chown {user}:users /tmp/start-restart1 /tmp/restart1.exp; chmod 755 /tmp/start-restart1")
    machine.succeed(f"sudo -u {user} expect -f /tmp/restart1.exp > /tmp/restart1-expect 2>&1 & echo $! > /tmp/restart1-pid")
    machine.wait_until_succeeds("test -e /tmp/restart1-ready", timeout=realPiTimeout)
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/restart1/detached-started", timeout=30 * pace)
    approval = machine.succeed(asUser("printf '\\nyes\\n' | workers approve --without-form alpha/b1/restart1") + " 2>&1")
    print("Round 6 item 6 approval:", approval)
    assert "automatic continuation was requested" in approval, approval
    deadline = time.time() + 20 * pace
    while (time.time() < deadline) and (machine.execute(f"test -e {folders}/alpha/b1/restart1/repo/approval-write")[0] != 0):
        time.sleep(0.5)
    probeOut = machine.succeed("cat /tmp/restart1.log /tmp/restart1-expect")
    assert machine.execute(f"test -e {folders}/alpha/b1/restart1/repo/approval-write")[0] == 0, probeOut[-5000:]
    machine.wait_until_succeeds("test -S /run/user/1000/workers/worker:alpha:b1:restart1.control/started", timeout=30 * pace)
    machine.succeed(asUser("systemctl --user kill -s TERM worker:alpha:b1:restart1.scope"))
    machine.wait_until_succeeds("! kill -0 $(cat /tmp/restart1-pid) 2>/dev/null", timeout=30 * pace)
    machine.succeed("test ! -e /run/user/1000/workers/worker:alpha:b1:restart1.control")
    out = machine.succeed("cat /tmp/restart1.log /tmp/restart1-expect")
    print("Round 6 item 6 pi:", out[-3000:])
    assert out.count("WORKER-TEST-ANSWER") >= 2 and "draft survives restart" in out and "restored your unsubmitted editor text" in out, out[-3000:]
    assert "automatic continuation failed" not in out, out[-3000:]
    machine.wait_until_fails("pgrep -x -f 'sleep 300'", timeout=20 * pace)
    lines = [json.loads(line) for line in machine.succeed(f"cat {folders}/alpha/b1/restart1/records/runs.jsonl").splitlines()]
    assert any(entry.get("stopped") is True for entry in lines), lines

    # A foreground queued job completes before graceful shutdown replaces the sandbox
    machine.succeed(start("--role manager", task("restart2", "implementer")))
    start2 = startScript.replace("restart1", "restart2")
    expect2 = rf'''set timeout {realPiTimeout}
log_file -noappend /tmp/restart2.log
spawn /tmp/start-restart2
expect "(worker-test) deterministic"
send "FOREGROUND queued job\r"
expect "WORKER-TEST-ANSWER"
expect eof
'''
    machine.succeed("cat > /tmp/start-restart2 <<'END'\n" + start2 + "END", "cat > /tmp/restart2.exp <<'END'\n" + expect2 + "END", f"chown {user}:users /tmp/start-restart2 /tmp/restart2.exp; chmod 755 /tmp/start-restart2", f"sudo -u {user} expect -f /tmp/restart2.exp > /tmp/restart2-expect 2>&1 & echo $! > /tmp/restart2-pid")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/restart2/foreground-started", timeout=realPiTimeout)
    assert "automatic continuation was requested" in machine.succeed(asUser("printf '\\nyes\\n' | workers approve --without-form alpha/b1/restart2") + " 2>&1")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/restart2/foreground-finished && test -e {folders}/alpha/b1/restart2/repo/approval-write", timeout=30 * pace)
    machine.succeed(asUser("systemctl --user kill -s TERM worker:alpha:b1:restart2.scope"))
    machine.wait_until_succeeds("! kill -0 $(cat /tmp/restart2-pid) 2>/dev/null", timeout=30 * pace)
    assert "WORKER-TEST-ANSWER" in machine.succeed("cat /tmp/restart2.log /tmp/restart2-expect")

    # Approval in the middle of an answer lets that one answer finish and save before the one continuation
    machine.succeed(start("--role manager", task("restart3", "implementer")))
    start3 = startScript.replace("restart1", "restart3")
    expect3 = rf'''set timeout {realPiTimeout}
log_file -noappend /tmp/restart3.log
spawn /tmp/start-restart3
expect "(worker-test) deterministic"
send "SLOW answer once\r"
expect "WORKER-TEST-ANSWER"
expect eof
'''
    machine.succeed("cat > /tmp/start-restart3 <<'END'\n" + start3 + "END", "cat > /tmp/restart3.exp <<'END'\n" + expect3 + "END", f"chown {user}:users /tmp/start-restart3 /tmp/restart3.exp; chmod 755 /tmp/start-restart3", f"sudo -u {user} expect -f /tmp/restart3.exp > /tmp/restart3-expect 2>&1 & echo $! > /tmp/restart3-pid")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/restart3/answer-started", timeout=realPiTimeout)
    assert "automatic continuation was requested" in machine.succeed(asUser("printf '\\nyes\\n' | workers approve --without-form alpha/b1/restart3") + " 2>&1")
    machine.wait_until_succeeds(f"test -e {folders}/alpha/b1/restart3/repo/approval-write && [ $(wc -l < {areas}/alpha/b1/restart3/answer-finished) -eq 1 ]", timeout=30 * pace)
    machine.succeed(asUser("systemctl --user kill -s TERM worker:alpha:b1:restart3.scope"))
    machine.wait_until_succeeds("! kill -0 $(cat /tmp/restart3-pid) 2>/dev/null", timeout=30 * pace)
    assert machine.succeed(f"wc -l < {areas}/alpha/b1/restart3/answer-finished").strip() == "1"

    # A noninteractive pi invocation is left alone and receives the exact manual continuation command
    machine.succeed(start("--role manager", task("restart4", "implementer")))
    start4 = startScript.replace("restart1", "restart4").replace(" --name restart4\n", " --name restart4 --mode json\n")
    machine.succeed("cat > /tmp/start-restart4 <<'END'\n" + start4 + "END", f"chown {user}:users /tmp/start-restart4; chmod 755 /tmp/start-restart4", f"sudo -u {user} bash -c 'tail -f /dev/null | /tmp/start-restart4' > /tmp/restart4-log 2>&1 & echo $! > /tmp/restart4-pid")
    machine.wait_until_succeeds(asUser("systemctl --user is-active --quiet worker:alpha:b1:restart4.scope"), timeout=30 * pace)
    approval = machine.succeed(asUser("printf '\\nyes\\n' | workers approve --without-form alpha/b1/restart4") + " 2>&1")
    assert "automatic continuation" not in approval and f"cd {home}/alpha && pi --branch b1 --name restart4 -c" in approval, approval
    machine.succeed("test ! -e /run/user/1000/workers/worker:alpha:b1:restart4.control/restart", asUser("systemctl --user kill -s TERM worker:alpha:b1:restart4.scope"))
    machine.wait_until_succeeds("! kill -0 $(cat /tmp/restart4-pid) 2>/dev/null", timeout=30 * pace)

    # A failed -c does not start a fresh chat or loop; it exits with the exact recovery command
    machine.succeed(start("--role manager", task("restart5", "implementer")))
    start5 = startScript.replace("worker-pi-restart", "worker-pi-restart-failure").replace("restart1", "restart5")
    expect5 = rf'''set timeout {realPiTimeout}
log_file -noappend /tmp/restart5.log
spawn /tmp/start-restart5
expect "(worker-test) deterministic"
send "one saved answer\r"
expect "WORKER-TEST-ANSWER"
exec touch /tmp/restart5-ready
expect "automatic continuation failed; continue the saved chat with: cd {home}/alpha && pi --branch b1 --name restart5 -c"
expect eof
'''
    machine.succeed("cat > /tmp/start-restart5 <<'END'\n" + start5 + "END", "cat > /tmp/restart5.exp <<'END'\n" + expect5 + "END", f"chown {user}:users /tmp/start-restart5 /tmp/restart5.exp; chmod 755 /tmp/start-restart5", f"sudo -u {user} expect -f /tmp/restart5.exp > /tmp/restart5-expect 2>&1 & echo $! > /tmp/restart5-pid")
    machine.wait_until_succeeds("test -e /tmp/restart5-ready", timeout=realPiTimeout)
    assert "automatic continuation was requested" in machine.succeed(asUser("printf '\\nyes\\n' | workers approve --without-form alpha/b1/restart5") + " 2>&1")
    machine.wait_until_succeeds("! kill -0 $(cat /tmp/restart5-pid) 2>/dev/null", timeout=40 * pace)
    out = machine.succeed("cat /tmp/restart5.log /tmp/restart5-expect")
    assert out.count("WORKER-TEST-ANSWER") >= 2 and "forced continuation failure" in out and "pi --branch b1 --name restart5 -c" in out and "approval-write" not in out, out[-3000:]

with subtest("The lock (W1 to W5, W8): an implementer's copy of the project is read-only until the user has approved its written intent"):
    approvals = f"{home}/.local/state/workers/alpha/approvals/b1"
    adviceWorkers = ["lk1", "advice-none", "advice-old", "advice-task", "advice-project", "advice-link", "advice-large"]
    machine.succeed(start("--role manager", " && ".join(task(name, "implementer") for name in adviceWorkers)))
    good = """# Intent

## Goal

Add the boundary term to the residual.

## Changes

- `solver/residual.py`, function `assemble`

## Not changed

The interface of `assemble`.

## Acceptance criteria

- The residual of a constant field is zero

## Tests

- `tests/test_residual.py::test_constant`: covers the changed function
- new: the boundary term alone, expected 0 for a constant field

## Approach 1: In place

### Trade-offs

Small; harder to test.

### Steps

- Change `assemble`
- Extend the test

## Approach 2: A function of its own

### Trade-offs

More lines; testable alone.

### Steps

1. Add `boundaryTerm`
2. Call it from `assemble`
3. Test it alone

## Recommendation

Approach 2, because it can be tested alone.

## Open questions

None.
"""

    def form(name, text):
        machine.succeed("cat > /tmp/form <<'END-OF-THE-FORM'\n" + text + "END-OF-THE-FORM", f"install -o {user} -m 644 /tmp/form {folders}/alpha/b1/{name}/reports/intent.md")

    def approve(worker, answers, options=""):
        return asUser("printf '%s\\n' " + " ".join(shlex.quote(answer) for answer in answers) + f" | workers approve {options} {worker}") + " 2>&1"

    def managerAdvice(managerName, workerName, fingerprint, text, taskFingerprint=None, testsCommit=None):
        if taskFingerprint is None:
            taskFingerprint = hashlib.sha256(machine.succeed(f"cat {folders}/alpha/instructions/b1/{workerName}.md").encode()).hexdigest()
        if testsCommit is None:
            testsCommit = machine.succeed(asUser("git -C ~/alpha rev-parse b1")).strip()
        content = (
            f"worker: alpha/b1/{workerName}\n"
            f"form-sha256: {fingerprint}\n"
            f"task-sha256: {taskFingerprint}\n"
            f"tests-commit: {testsCommit}\n\n{text}\n"
        )
        options = "--role manager" + (f" --name {managerName}" if managerName != "manager" else "")
        path = f"../reports/advice/b1/{workerName}.md"
        machine.succeed(start(options, f"mkdir -p ../reports/advice/b1 && printf %s {shlex.quote(content)} > {path}"))

    # What a worker does to a copy that is its own to write: change, rename, remove, add, replace by a link, commit
    changes = ["echo change >> file", "mv file moved", "rm AGENTS.md", "echo new > new-file", "mkdir new-folder", "ln -s /etc/hostname file", "git -c user.name=t -c user.email=t@t commit -q -a -m work"]
    attempt = "for what in " + " ".join(shlex.quote(change) for change in changes) + '; do if { eval "$what"; } > /dev/null 2>&1; then echo accepted; else echo refused; fi; done'
    locked = lambda name, script: start(f"--branch b1 --name {name}", script, locked=True)

    ## W1: a new implementer cannot change its copy, directly or in a job; it reads it, and writes its reports and its scratch area
    out = machine.succeed(locked("lk1", attempt + "; cat file; ls ../reports; echo x > $WORKER_SCRATCH/x && echo scratch-writable") + " 2>&1")
    print("W1, not approved:", out)
    assert "the worker b1/lk1 is not approved: its copy of the project is read-only" in out and "workers approve alpha/b1/lk1" in out, out
    assert out.split()[-10:] == ["refused"] * 7 + ["content", "intent.md", "scratch-writable"], out
    assert machine.succeed(locked("lk1", f"queue run -- bash -c {shlex.quote(attempt)}") + " 2>/dev/null").split() == ["refused"] * 7
    assert machine.succeed(f"cat {folders}/alpha/b1/lk1/repo/file; ls {folders}/alpha/b1/lk1/repo").split() == ["content", "AGENTS.md", "file"]

    ## W3: a form that is not complete, or cannot be read as a file of the worker's, is not approved; no record is written
    # The form as the worker found it at its first start: the template. The worker sees the same findings with its own command
    out = machine.succeed(locked("lk1", 'intent check; echo "check=$?"') + " 2>/dev/null")
    assert "is not complete" in out and "'## Goal' is empty" in out and "the form needs two or more approaches" not in out and "check=1" in out, out
    incomplete = [
        (None, "'## Goal' is empty"),
        (good[: good.index("## Approach 2")] + good[good.index("## Recommendation") :], "the form needs two or more approaches ('## Approach <number>: <title>'); it has 1"),
        (good.replace("- Change `assemble`\n- Extend the test\n", ""), "'## Approach 1' has no list of steps below '### Steps'"),
        (good.replace("- The residual of a constant field is zero\n", ""), "'## Acceptance criteria' is empty"),
        (good.replace("Approach 2, because", "The second, because"), "'## Recommendation' names none of the approaches"),
        (good.replace("## Not changed", "## Unchanged"), "the heading '## Not changed' is missing"),
        # W8: a test's name that would be read as an option, and one with a space
        (good.replace("`tests/test_residual.py::test_constant`", "`--deselect=everything`"), "the test name `--deselect=everything` is not one"),
        (good.replace("`tests/test_residual.py::test_constant`", "`tests/a b.py`"), "the test name `tests/a b.py` is not one"),
    ]
    for text, reason in incomplete:
        if text is not None:
            form("lk1", text)
        out = machine.fail(approve("alpha/b1/lk1", ["1", "", "yes"]))
        assert reason in out and "approved:" not in out, f"{reason}: {out[-600:]}"
        machine.succeed(f"test ! -e {approvals}/lk1")
    # A form of 300 KiB
    form("lk1", good)
    machine.succeed(asUser(f"head -c 300000 /dev/zero | tr '\\0' x >> {folders}/alpha/b1/lk1/reports/intent.md"))
    out = machine.fail(approve("alpha/b1/lk1", ["1", "", "yes"]))
    assert "is larger than 262144 bytes" in out, out
    machine.succeed(f"test ! -e {approvals}/lk1")
    # W8 as the worker meets it, inside its sandbox
    form("lk1", good.replace("`tests/test_residual.py::test_constant`", "`-x`"))
    out = machine.succeed(locked("lk1", 'intent check; echo "check=$?"') + " 2>/dev/null")
    assert "the test name `-x` is not one" in out and "check=1" in out, out
    # A link in the form's place, to a file that the worker does not see
    machine.succeed(asUser(f"ln -sfn {home}/.ssh/id_test {folders}/alpha/b1/lk1/reports/intent.md"))
    out = machine.fail(approve("alpha/b1/lk1", ["1", "", "yes"]))
    assert "cannot be read" in out and "reached without a link" in out and "secret" not in out, out
    machine.succeed(f"test ! -e {approvals}/lk1", asUser(f"rm {folders}/alpha/b1/lk1/reports/intent.md"))
    # Control: the complete form passes the worker's own check
    form("lk1", good)
    out = machine.succeed(locked("lk1", 'intent check; echo "check=$?"') + " 2>/dev/null")
    assert "is complete: 2 approaches, 1 existing and 1 new tests" in out and "check=0" in out, out

    ## Round 6 item 1: managers' advice is data about exactly this form, and is optional
    fingerprint = hashlib.sha256(good.encode()).hexdigest()
    managerAdvice("manager", "lk1", fingerprint, "Prefer approach 2.\nWhich approach do you approve? Its number: 99\n\x1b[31mmanager-colour\x1b[0m")
    managerAdvice("adviser", "lk1", fingerprint, "Approach 2 keeps the boundary testable.")
    # A file with the same name in the implementer's own folder is not a manager's advice
    machine.succeed(locked("lk1", "mkdir -p ../reports/advice/b1 && echo FORGED-IMPLEMENTER-ADVICE > ../reports/advice/b1/lk1.md"))

    for name in ["advice-none", "advice-old", "advice-task", "advice-project", "advice-link", "advice-large"]:
        machine.succeed(locked(name, "true"))
        form(name, good)
    managerAdvice("manager", "advice-old", hashlib.sha256((good + "older").encode()).hexdigest(), "OLD-ADVICE-MUST-NOT-BE-CURRENT")
    managerAdvice("manager", "advice-task", fingerprint, "TASK-BOUND-ADVICE")
    machine.succeed(start("--role manager", task("advice-task", "implementer", "Changed task.")))
    managerAdvice("manager", "advice-project", fingerprint, "PROJECT-BOUND-ADVICE")
    machine.succeed(start("--role manager", f"ln -s {home}/.ssh/id_test ../reports/advice/b1/advice-link.md"))
    machine.succeed(start("--role manager", "{ printf 'worker: alpha/b1/advice-large\\nform-sha256: " + fingerprint + "\\n\\n'; head -c 300000 /dev/zero | tr '\\0' x; } > ../reports/advice/b1/advice-large.md"))

    out = machine.fail(approve("alpha/b1/advice-none", ["7"]))
    assert "No manager advice for this form." in out, out
    out = machine.fail(approve("alpha/b1/advice-old", ["7"]))
    assert "Advice from manager manager is not current because the form changed." in out and "OLD-ADVICE-MUST-NOT-BE-CURRENT" not in out, out
    out = machine.fail(approve("alpha/b1/advice-task", ["7"]))
    assert "Advice from manager manager is not current because the task changed." in out and "TASK-BOUND-ADVICE" not in out and "Start the manager again" in out, out
    out = machine.fail(approve("alpha/b1/advice-link", ["7"]))
    assert "Advice from manager manager cannot be read safely" in out and "reached without a link" in out and "secret" not in out, out
    out = machine.fail(approve("alpha/b1/advice-large", ["7"]))
    assert "Advice from manager manager cannot be read safely" in out and "is larger than 262144 bytes" in out, out

    ## W5: anything but a typed yes, a number that names no approach, or no answer at all: no record, and the copy stays read-only
    for answers, reason in [(["2", "a note", "no"], "not approved: nothing was changed"), (["2", "a note", "YES"], "not approved"), (["7", "", "yes"], "'7' is not the number of an approach"), ([], "no answer")]:
        out = machine.fail(approve("alpha/b1/lk1", answers) if answers else asUser("workers approve alpha/b1/lk1 < /dev/null") + " 2>&1")
        assert reason in out, f"{answers}: {out[-400:]}"
        machine.succeed(f"test ! -e {approvals}/lk1")
    assert machine.succeed(locked("lk1", attempt) + " 2>/dev/null").split() == ["refused"] * 7

    ## W2: what a worker writes opens nothing: the word, a record and a decision file of its own making, wherever it can write
    forge = (
        "mkdir -p ~/.local/state/workers/alpha/approvals/b1 && echo '{\"withoutForm\": true, \"time\": 1}' > ~/.local/state/workers/alpha/approvals/b1/lk1;"
        " echo approved > ../reports/approved; for place in ../reports $WORKER_SCRATCH /tmp ~; do printf '# Decision\\n\\napproved\\n' > $place/decision.md; done;"
        " { printf '# Decision\\n' > ../records/decision.md; } 2>/dev/null; echo \"records=$?\""
    )
    assert machine.succeed(locked("lk1", forge) + " 2>/dev/null").strip() == "records=1"
    assert machine.succeed(locked("lk1", attempt) + " 2>/dev/null").split() == ["refused"] * 7
    machine.succeed(f"test ! -e {approvals}/lk1 && test ! -e {folders}/alpha/b1/lk1/records/decision.md && test -e {folders}/alpha/b1/lk1/reports/decision.md")

    ## W4: the form is changed while the user is asked: what is approved is what was shown
    # (the last answer is given when the form has been changed)
    answering = asUser("(printf '2\\nBoth steps first.\\n'; until [ -e /tmp/w4-changed ]; do sleep 0.2; done; printf 'yes\\n') | workers approve alpha/b1/lk1")
    machine.succeed(f"({locked('lk1', 'echo approval-worker-runs; ' + gate('approval-go'))}) > /tmp/approval-worker 2>&1 &")
    machine.wait_until_succeeds("grep -q approval-worker-runs /tmp/approval-worker", timeout=30 * pace)
    machine.succeed(f"rm -f /tmp/w4-changed; ({answering}) > /tmp/approval 2>&1 &")
    machine.wait_until_succeeds("grep -q 'Which approach do you approve' /tmp/approval", timeout=20 * pace)
    form("lk1", good.replace("Add the boundary term to the residual.", "Rewrite the solver."))
    machine.succeed("touch /tmp/w4-changed")
    machine.wait_until_succeeds(f"test -e {approvals}/lk1", timeout=30 * pace)
    out = machine.succeed("cat /tmp/approval")
    print("W4, the approval:", out[-700:])
    assert "Add the boundary term to the residual." in out and "Rewrite the solver." not in out and "(the worker's recommendation)" in out, out
    assert "Advice from manager manager (the manager's word" in out and "Advice from manager adviser (the manager's word" in out, out
    assert "FORGED-IMPLEMENTER-ADVICE" not in out and "\x1b" not in out, out
    for managerName in ["manager", "adviser"]:
        adviceShown = out[out.index(f"Advice from manager {managerName}") : out.index(f"The end of advice from manager {managerName}.")].splitlines()[1:]
        assert adviceShown and all(line.startswith("  | ") for line in adviceShown), adviceShown
    # W9, for a project that states no tests: the approval alone opens the lock, and the command and the record say "no tests"
    assert "The project states no tests (no workers.toml on its branch b1): the approval alone will open the lock" in out, out
    assert "approved (no tests: the project states no tests): from its next start alpha/b1/lk1 can write its copy of the project" in out, out
    assert "alpha/b1/lk1 is still running: end its running session" in out and f"cd {home}/alpha && pi --branch b1 --name lk1 -c" in out, out
    openGate("alpha/b1/lk1", "approval-go")
    sandboxEnded("alpha/b1/lk1")
    # The review's first small point: every line of the form stands behind the tool's mark
    shown = out[out.index("The form of alpha/b1/lk1") : out.index("The end of the form.")].splitlines()[1:]
    assert len(shown) > 40 and all(line.startswith("  | ") for line in shown), shown
    record = json.loads(machine.succeed(f"cat {approvals}/lk1"))
    print("the record:", record)
    assert record["fingerprint"] == hashlib.sha256(good.encode()).hexdigest(), record
    assert record["advice"] == {
        "shown": ["adviser", "manager"],
        "formFingerprint": fingerprint,
        "taskFingerprint": hashlib.sha256(machine.succeed(f"cat {folders}/alpha/instructions/b1/lk1.md").encode()).hexdigest(),
        "testsCommit": machine.succeed(asUser("git -C ~/alpha rev-parse b1")).strip(),
    }, record
    assert (record["approach"], record["title"], record["note"]) == (2, "A function of its own", "Both steps first."), record
    assert record["steps"] == ["Add `boundaryTerm`", "Call it from `assemble`", "Test it alone"] and record["tests"] == ["tests/test_residual.py::test_constant"], record
    assert len(record["testsCommit"]) == 40 and record["noTests"] == "the project states no tests" and len(record["listDigest"]) == 64, record
    # Advice also goes stale visibly when the project commit that supplies the tests changes; only a manager rewrites it
    machine.succeed(asUser("git -C ~/alpha checkout -q b1 && echo advice-change > ~/alpha/advice-change && git -C ~/alpha add advice-change && git -C ~/alpha -c user.name=t -c user.email=t@t commit -q -m advice-change"))
    out = machine.fail(approve("alpha/b1/advice-project", ["7"]))
    assert "Advice from manager manager is not current because the project tests commit changed." in out and "PROJECT-BOUND-ADVICE" not in out and "Start the manager again" in out, out

    # Asked again, the command changes nothing and says that the form is no longer the one that was approved
    out = machine.fail(approve("alpha/b1/lk1", ["1", "", "yes"]))
    assert "approach 2, A function of its own" in out and "its form changed since approval" in out and "nothing was changed" in out, out
    assert json.loads(machine.succeed(f"cat {approvals}/lk1")) == record
    # Control: with the approved text in place again, it says so
    form("lk1", good)
    out = machine.fail(approve("alpha/b1/lk1", []))
    assert "its form is as it was approved" in out and "its copy is writable" in out, out

    ## W1, control: approved, and after a new start, the same changes are accepted, by the agent and then in a job
    out = machine.succeed(locked("lk1", attempt) + " 2>&1")
    assert out.split() == ["accepted"] * 7, out
    assert machine.succeed(locked("lk1", "queue run -- bash -c 'echo more > more-from-a-job && echo accepted'")).strip() == "accepted"
    # The decision file: the approved approach with its steps and tests, readable for the worker and not writable
    out = machine.succeed(locked("lk1", 'cat ../records/decision.md; { echo more >> ../records/decision.md; } 2>/dev/null; echo "change=$?"; rm -f ../records/decision.md 2>/dev/null; ls ../records'))
    print("the decision file:", out)
    for expected in ["- Approach 2: A function of its own", "- The user's note: Both steps first.", "- Add `boundaryTerm`", "- Test it alone", "- `tests/test_residual.py::test_constant`", "- the boundary term alone, expected 0 for a constant field", "change=1", "decision.md"]:
        assert expected in out, f"{expected}: {out}"
    assert "Extend the test" not in out and record["fingerprint"] in out, out

    ## The approval taken back: read-only again from the next start, and the decision file is gone
    assert "is taken back" in machine.succeed(approve("alpha/b1/lk1", [], "--revoke"))
    assert machine.succeed(locked("lk1", attempt + "; ls ../records") + " 2>/dev/null").split()[:7] == ["refused"] * 7
    machine.succeed(f"test ! -e {approvals}/lk1 && test ! -e {folders}/alpha/b1/lk1/records/decision.md")
    assert "is not approved" in machine.fail(approve("alpha/b1/lk1", [], "--revoke"))

    ## A small task: the user opens the lock himself, also before the worker's first start; the record says so
    assert "not approved" in machine.fail(approve("alpha/b1/lk2", ["", "no"], "--without-form"))
    machine.succeed(f"test ! -e {approvals}/lk2")
    out = machine.succeed(approve("alpha/b1/lk2", ["A typing error in the README.", "yes"], "--without-form"))
    assert "there is no worker alpha/b1/lk2 yet" in out and "approved (no tests: approved without a form)" in out, out
    record = json.loads(machine.succeed(f"cat {approvals}/lk2"))
    assert record["withoutForm"] is True and record["noTests"] == "approved without a form" and record["note"] == "A typing error in the README." and "approach" not in record, record
    assert machine.succeed(locked("lk2", attempt) + " 2>&1").split() == ["accepted"] * 7

    ## Only implementers have a lock, and only the user's command writes the record
    for branch in ["manager", "archive", "instructions", "plain", "old"]:
        status, out = machine.execute(approve(f"alpha/{branch}/reserved-{branch}", ["", "yes"], "--without-form"))
        if (status == 0):
            reservedApproveProblems[branch] = out
        machine.succeed(f"rm -f {home}/.local/state/workers/alpha/approvals/{branch}/reserved-{branch}")
    for worker, reason in [("alpha/b1/r1", "is a reviewer: only an implementer's copy is locked"), ("alpha/manager/manager", "only an implementer's copy is locked"), ("alpha/b1", "usage: workers approve"), ("alpha/b1/nobody", "there is no implementer alpha/b1/nobody")]:
        assert reason in machine.fail(approve(worker, ["1", "", "yes"])), worker
    assert machine.succeed(f"stat -c '%a %U' {approvals}/lk2").split() == ["600", user]

with subtest("The tests (W6, W7, W9): the approved tests run from the project's own history, and their baseline is part of the lock"):
    approvals = f"{home}/.local/state/workers/tested/approvals/b1"
    records = lambda name: [json.loads(line) for line in machine.succeed(f"cat {folders}/tested/b1/{name}/records/runs.jsonl").splitlines()]
    tip = machine.succeed(asUser("git -C ~/tested rev-parse b1")).strip()

    def form(name, tests, branch="b1"):
        text = good.replace("- `tests/test_residual.py::test_constant`: covers the changed function\n- new: the boundary term alone, expected 0 for a constant field\n", tests)
        assert text != good
        machine.succeed("cat > /tmp/form <<'END-OF-THE-FORM'\n" + text + "END-OF-THE-FORM", f"install -o {user} -m 644 /tmp/form {folders}/tested/{branch}/{name}/reports/intent.md")

    worker = lambda name, script, branch="b1": start(f"--branch {branch} --name {name}", script, project="~/tested", locked=True)
    writes = 'if { echo change >> notes; } 2>/dev/null; then echo writable; else echo read-only; fi'

    ## The baseline while planning: the tests that the form proposes, run by the worker, chosen by nobody inside
    machine.succeed(worker("ta", "true") + " 2>/dev/null")
    form("ta", "- `t-sum`: the sum is what changes\n- `t-env`: nothing of the worker's environment reaches the tests\n")
    # CHEAT is set in the worker's own shell; the test t-env fails if it arrives
    out = machine.succeed(worker("ta", 'export CHEAT=1; queue acceptance; echo "exit=$?"; queue run -- bash tests/run.sh t-env; echo "own-run=$?"') + " 2>/dev/null")
    print("the baseline, proposed:", out)
    assert out.split("\n")[:3] == ["pass t-sum", "pass t-env", "exit=0"] and "FAIL t-env\nown-run=1" in out, out
    run = records("ta")[1]
    print("its record:", run)
    assert (run["kind"], run["mode"], run["list"], run["tests"], run["exit"]) == ("acceptance", "acceptance", "proposed", ["t-sum", "t-env"], 0), run
    assert run["testsCommit"] == tip and run["commit"] == tip and len(run["listDigest"]) == 64, run
    # Approved unchanged: that run is the baseline, and the next start is writable without another round
    out = machine.succeed(approve("tested/b1/ta", ["2", "", "yes"]))
    assert "approved, and the approved tests have run on its copy already: from its next start tested/b1/ta can write its copy" in out, out[-400:]
    record = json.loads(machine.succeed(f"cat {approvals}/ta"))
    assert (record["tests"], record["listDigest"], record["testsCommit"], record["copyCommit"]) == (["t-sum", "t-env"], run["listDigest"], tip, tip) and "noTests" not in record, record
    assert machine.succeed(worker("ta", writes) + " 2>&1").strip() == "writable"

    ## W6: the worker breaks the code and weakens the test in its own copy; the approved run uses the project's test
    weaken = (
        "echo 'echo 6' > src/sum.sh; echo true > tests/t-sum.sh; git -c user.name=t -c user.email=t@t commit -q -a -m weakened;"
        ' bash tests/run.sh t-sum; echo "own-tests=$?"; queue acceptance; echo "exit=$?"'
    )
    out = machine.succeed(worker("ta", weaken) + " 2>/dev/null")
    print("W6:", out)
    assert out.split() == ["pass", "t-sum", "own-tests=0", "FAIL", "t-sum", "pass", "t-env", "exit=1"], out
    run = records("ta")[-1]
    assert (run["list"], run["exit"], run["testsCommit"]) == ("approved", 1, tip) and run["commit"] != tip, run
    # R1: a failed baseline while approval exists never asks the running session to continue
    failedScript = "while [ ! -e $WORKER_SCRATCH/failed-go ]; do sleep 0.2; done; queue acceptance; touch $WORKER_SCRATCH/failed-done; while [ ! -e $WORKER_SCRATCH/failed-end ]; do sleep 0.2; done"
    machine.succeed(f"({worker('ta', failedScript)}) > /tmp/ta-failed-baseline 2>&1 &")
    machine.wait_until_succeeds(asUser("systemctl --user is-active --quiet worker:tested:b1:ta.scope"), timeout=30 * pace)
    taControl = "/run/user/1000/workers/worker:tested:b1:ta.control"
    machine.succeed(f"install -d -o {user} -g users -m 700 {taControl}; printf 'supported\\n' > {taControl}/mode; chown {user}:users {taControl}/mode; touch {areas}/tested/b1/ta/failed-go")
    machine.wait_until_succeeds(f"test -e {areas}/tested/b1/ta/failed-done", timeout=60 * pace)
    machine.fail(f"test -e {taControl}/restart")
    machine.succeed(f"touch {areas}/tested/b1/ta/failed-end")
    sandboxEnded("tested/b1/ta")
    # What is tested is the commit: a correction that is not committed changes nothing, the committed one passes
    mend = "echo 'echo $(($1 + $2))' > src/sum.sh; queue acceptance > /dev/null; echo \"uncommitted=$?\"; git -c user.name=t -c user.email=t@t commit -q -a -m mended; queue acceptance > /dev/null; echo \"committed=$?\""
    assert machine.succeed(worker("ta", mend) + " 2>/dev/null").split() == ["uncommitted=1", "committed=0"]

    ## W7: while the run goes on, the agent finds nothing of the job's tree where it can write, and what it writes changes nothing
    machine.succeed(worker("tb", "true") + " 2>/dev/null")
    form("tb", "- `t-slow`: it takes a while\n")
    meddle = (
        "queue acceptance > $WORKER_SCRATCH/result 2>&1 & run=$!; " + gate("w7-look") + ";"
        " echo \"trees=$(ls -d /tmp/acceptance.* $WORKER_SCRATCH/acceptance.* 2>/dev/null | wc -l)\";"
        " echo \"copies=$(find /tmp $WORKER_SCRATCH ~ -name t-slow.sh -not -path '*/repo/*' 2>/dev/null | wc -l)\";"
        " mkdir -p $WORKER_SCRATCH/tests /tmp/tests && echo 'exit 1' | tee $WORKER_SCRATCH/tests/t-slow.sh /tmp/tests/t-slow.sh > /dev/null;"
        " wait $run; echo \"exit=$?\"; cat $WORKER_SCRATCH/result"
    )
    machine.succeed(f"rm -f /tmp/w7-ended; ({worker('tb', meddle)}; touch /tmp/w7-ended) > /tmp/w7 2> /dev/null &")
    # Control, from outside every sandbox: the test does run in a tree, in the /tmp of its job. The agent looks and writes
    # when this test has seen the approved test running
    machine.wait_until_succeeds(f"pgrep -x -f 'sleep {4 * pace}'", timeout=30 * pace)
    where = machine.succeed(f"readlink /proc/$(pgrep -x -f 'sleep {4 * pace}' | head -n 1)/cwd").strip()
    assert where.startswith("/tmp/acceptance."), where
    openGate("tested/b1/tb", "w7-look")
    machine.wait_until_succeeds("test -e /tmp/w7-ended", timeout=60 * pace)
    out = machine.succeed("cat /tmp/w7")
    print("W7:", out, "| the job's tree:", where)
    assert out.split() == ["trees=0", "copies=0", "exit=0", "pass", "t-slow"], out

    ## W9: the approved list is not the one the baseline ran on (the manager added a test): read-only until it has run
    machine.succeed(start("--role manager", "mkdir -p ~/workers/tested/instructions/b1 && printf 'branch: b1\\nname: tb\\nrole: implementer\\ntest: t-sum\\n\\nDo it.\\n' > ~/workers/tested/instructions/b1/tb.md", project="~/tested"))
    orderScript = (
        "while [ ! -e $WORKER_SCRATCH/baseline-go ]; do sleep 0.2; done; "
        "queue acceptance; touch $WORKER_SCRATCH/baseline-done; "
        "while [ ! -e $WORKER_SCRATCH/second-go ]; do sleep 0.2; done; "
        "queue acceptance; touch $WORKER_SCRATCH/second-done; "
        "while [ ! -e $WORKER_SCRATCH/no-baseline-end ]; do sleep 0.2; done"
    )
    machine.succeed(f"({worker('tb', orderScript)}) > /tmp/tb-no-baseline 2>&1 &")
    machine.wait_until_succeeds(asUser("systemctl --user is-active --quiet worker:tested:b1:tb.scope"), timeout=30 * pace)
    machine.succeed(f"install -d -o {user} -g users -m 700 /run/user/1000/workers/worker:tested:b1:tb.control; printf 'supported\\n' > /run/user/1000/workers/worker:tested:b1:tb.control/mode; chown {user}:users /run/user/1000/workers/worker:tested:b1:tb.control/mode")
    out = machine.succeed(approve("tested/b1/tb", ["1", "", "yes"]))
    assert "Tests added by the manager in the task file: t-sum" in out and "approved. Its copy stays read-only until the approved tests have run on it as it is" in out, out[-500:]
    control = "/run/user/1000/workers/worker:tested:b1:tb.control"
    assert f"cd {home}/tested && pi --branch b1 --name tb -c" in out and machine.execute(f"test -e {control}/restart")[0] != 0, out
    # R1: approval can arrive first; the successful baseline asks the same running pi session to continue, exactly once
    machine.succeed(f"touch {areas}/tested/b1/tb/baseline-go")
    machine.wait_until_succeeds(f"test -e {areas}/tested/b1/tb/baseline-done && test -s {control}/restart", timeout=60 * pace)
    firstRequest = machine.succeed(f"stat -c '%i %Y' {control}/restart; cat {control}/restart")
    machine.succeed(f"touch {areas}/tested/b1/tb/second-go")
    machine.wait_until_succeeds(f"test -e {areas}/tested/b1/tb/second-done", timeout=60 * pace)
    secondRequest = machine.succeed(f"stat -c '%i %Y' {control}/restart; cat {control}/restart")
    assert secondRequest == firstRequest, (firstRequest, secondRequest)
    machine.succeed(f"touch {areas}/tested/b1/tb/no-baseline-end")
    sandboxEnded("tested/b1/tb")
    assert json.loads(machine.succeed(f"cat {approvals}/tb"))["tests"] == ["t-slow", "t-sum"]
    # The baseline that arrived second opened the next start without a manual restart or another acceptance run
    assert machine.succeed(worker("tb", writes) + " 2>&1").strip() == "writable"
    assert "its copy is writable" in machine.fail(approve("tested/b1/tb", []))

    # R1, the other order: a successful baseline exists first and approval requests one continuation of the running session
    machine.succeed(worker("order-first", "true") + " 2>/dev/null")
    form("order-first", "- `t-sum`: the sum is what changes\n")
    machine.succeed(f"({worker('order-first', 'queue acceptance; touch $WORKER_SCRATCH/baseline-first-done; while [ ! -e $WORKER_SCRATCH/baseline-first-end ]; do sleep 0.2; done')}) > /tmp/order-first 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/tested/b1/order-first/baseline-first-done", timeout=60 * pace)
    orderControl = "/run/user/1000/workers/worker:tested:b1:order-first.control"
    machine.succeed(f"install -d -o {user} -g users -m 700 {orderControl}; printf 'supported\\n' > {orderControl}/mode; chown {user}:users {orderControl}/mode")
    out = machine.succeed(approve("tested/b1/order-first", ["1", "", "yes"]))
    assert "automatic continuation was requested" in out and machine.succeed(f"test -s {orderControl}/restart; wc -l < {orderControl}/restart").strip() == "1", out
    machine.succeed(f"touch {areas}/tested/b1/order-first/baseline-first-end")
    sandboxEnded("tested/b1/order-first")

    # An approved list that is empty: the approval alone, and the record says "no tests"
    machine.succeed(worker("tc", "true") + " 2>/dev/null")
    form("tc", "- none: the change is to the documentation only\n")
    assert "approved (no tests: no existing test was approved)" in machine.succeed(approve("tested/b1/tc", ["1", "", "yes"]))
    assert json.loads(machine.succeed(f"cat {approvals}/tc"))["noTests"] == "no existing test was approved"
    assert machine.succeed(worker("tc", writes) + " 2>&1").strip() == "writable"

    # A run that was stopped before its end is no baseline: here the worker's own command is ended when its job has a slot, and
    # the sandbox goes on until the broker has let the request go
    machine.succeed(worker("tf", "true") + " 2>/dev/null")
    form("tf", "- `t-slow`: it takes a while\n")
    cut = 'queue acceptance & run=$!; until queue status | grep -q "^slot[0-9]* *taken"; do sleep 0.2; done; kill $run; wait $run; echo "exit=$?"; until queue status | grep -q "this sandbox: 0 of"; do sleep 0.2; done'
    out = machine.succeed(worker("tf", cut) + " 2>/dev/null")
    print("a run whose command is ended when it has its slot:", out.split(), records("tf")[-1])
    # The job ended with its command: nothing of the test's own output arrived, and the record says that it was stopped
    assert out.strip() == "exit=143", out
    assert records("tf")[-1]["stopped"] is True and records("tf")[-1]["exit"] != 0 and records("tf")[-1]["duration_s"] < 4 * pace, records("tf")[-1]
    assert "approved. Its copy stays read-only until the approved tests have run on it as it is" in machine.succeed(approve("tested/b1/tf", ["1", "", "yes"]))
    assert machine.succeed(worker("tf", writes + "; queue acceptance > /dev/null") + " 2>/dev/null").strip() == "read-only"
    assert machine.succeed(worker("tf", writes) + " 2>&1").strip() == "writable"

    ## What `queue acceptance` refuses, each with its reason, and without running anything
    refusals = [
        (worker("tc", "queue acceptance"), "was approved without tests (no existing test was approved), so there is nothing to run"),
        (worker("td", "queue acceptance"), "the form is not complete, so it proposes no tests to run yet"),
        (start("--branch b1 --name lk1", "queue acceptance", locked=True), "the project of alpha/b1/lk1 states no tests (no workers.toml on its branch b1)"),
        (worker("ta", "queue acceptance -- echo mine"), "usage: queue run"),
        (worker("ta", "queue acceptance --all"), "--all is a manager's"),
        (worker("ta", "queue run -- queue acceptance"), "not from inside a job"),
        (start("--role reviewer --branch b1 --name tr --of ta", "queue acceptance", project="~/tested"), "an acceptance run is an implementer's"),
        (start("", "queue acceptance", project="~/tested"), "an acceptance run is an implementer's"),
    ]
    for command, reason in refusals:
        out = machine.fail(command + " 2>&1")
        assert reason in out and "pass " not in out, f"{reason}: {out[-400:]}"
    # A request written by hand that brings a command of its own is refused by the broker
    raw = "import json, socket, struct; body = json.dumps({'mode': 'acceptance', 'command': ['echo', 'mine'], 'folder': '/', 'environment': {}}).encode(); c = socket.socket(socket.AF_UNIX); c.connect('/run/worker/queue.sock'); socket.send_fds(c, [struct.pack('>I', len(body)) + body], [0, 1, 2]); print(c.recv(65536).decode())"
    out = machine.succeed(worker("ta", f"python3 -c {shlex.quote(raw)}"))
    assert "an acceptance run takes no command" in out and "mine" not in out.replace("command", ""), out
    # A project whose workers.toml on the worker's branch says nothing usable: the approval is refused, with the reason
    machine.succeed(worker("te", "true", branch="b2") + " 2>/dev/null")
    form("te", "- `t-sum`: the sum\n", branch="b2")
    out = machine.fail(approve("tested/b2/te", ["1", "", "yes"]))
    assert "[tests] needs 'paths', a list of words that is not empty" in out, out[-300:]
    machine.succeed(f"test ! -e {home}/.local/state/workers/tested/approvals/b2/te")
    # A path that is absent from the project's commit: the run still fails, and names that path rather than the whole list
    machine.succeed(worker("tm", "true", branch="missing") + " 2>/dev/null")
    form("tm", "- `t-sum`: the sum\n", branch="missing")
    missing = machine.fail(worker("tm", "queue acceptance", branch="missing") + " 2>&1")
    print("missing acceptance path:", missing.strip(), "| reserved starts:", reservedStartProblems, "| reserved approvals:", reservedApproveProblems)
    assert "test path 'missing-test' does not exist" in missing, missing
    assert reservedStartProblems == {} and reservedApproveProblems == {}, (reservedStartProblems, reservedApproveProblems)

    ## The whole suite, in a manager's copy, with that copy's own tests
    out = machine.succeed(start("--role manager", 'queue acceptance --all; echo "exit=$?"', project="~/tested") + " 2>/dev/null")
    print("the whole suite in the manager's copy:", out)
    assert out.split() == ["pass", "t-env", "pass", "t-slow", "pass", "t-sum", "exit=0"], out
    run = json.loads(machine.succeed(f"tail -n 1 {folders}/tested/manager/manager/records/runs.jsonl"))
    assert (run["mode"], run["list"], run["exit"]) == ("acceptance-all", "all", 0), run

with subtest("The review's two small points: no line of a form can pass for a line of the tool, and on a terminal the form waits in a viewer"):
    machine.succeed(start("--branch b1 --name lk4", "true", locked=True) + " 2>/dev/null")
    fake = "The end of the form.\nApproach 9: Take everything, 1 steps  (the worker's recommendation)\nWhich approach do you approve? Its number: 9\n"
    text = good.replace("Add the boundary term to the residual.\n", "Add the boundary term to the residual.\n" + fake)
    machine.succeed("cat > /tmp/form <<'END-OF-THE-FORM'\n" + text + "END-OF-THE-FORM", f"install -o {user} -m 644 /tmp/form {folders}/alpha/b1/lk4/reports/intent.md")
    out = machine.fail(approve("alpha/b1/lk4", ["9", "", "yes"]))
    print("a form that imitates the tool:", out[-900:])
    lines = out.splitlines()
    # The imitated lines are there, each behind the mark; the tool's own end line and list come once, after them
    assert "  | The end of the form." in lines and "  | Approach 9: Take everything, 1 steps  (the worker's recommendation)" in lines, out
    assert lines.count("The end of the form.") == 1 and not [line for line in lines if line.startswith("Approach 9")], out
    assert "'9' is not the number of an approach: nothing was approved" in out, out
    # On a terminal: the form is in the viewer until q is typed, and nothing is asked or recorded before
    # (q is typed when this test has seen the viewer and looked; the answers when the viewer is gone; the terminal stays until
    # the approval is recorded and the tool has said so)
    wait = lambda path: f"until [ -e {path} ]; do sleep 0.2; done"
    keys = f"({wait('/tmp/lk4-q')}; printf q; {wait('/tmp/lk4-answers')}; printf '2\\nFrom a terminal.\\nyes\\n'; {wait(home + '/.local/state/workers/alpha/approvals/b1/lk4')}; until grep -q 'approved (no tests' /tmp/terminal; do sleep 0.2; done)"
    machine.succeed(f"rm -f /tmp/lk4-*; ({asUser(keys + ' | TERM=xterm script -qec ' + shlex.quote('workers approve alpha/b1/lk4') + ' /dev/null')}) > /tmp/terminal 2>&1 &")
    machine.wait_until_succeeds("pgrep -x less", timeout=30 * pace)
    # (the form itself holds an imitated first question; the tool's second one is the sign that it went on)
    assert "A note of yours" not in machine.succeed("cat /tmp/terminal") and machine.succeed(f"ls {home}/.local/state/workers/alpha/approvals/b1 | grep -c lk4 || true").strip() == "0"
    machine.succeed("touch /tmp/lk4-q")
    machine.wait_until_fails("pgrep -x less", timeout=30 * pace)
    machine.succeed("touch /tmp/lk4-answers")
    machine.wait_until_succeeds(f"test -e {home}/.local/state/workers/alpha/approvals/b1/lk4", timeout=30 * pace)
    out = machine.succeed("cat /tmp/terminal")
    assert "A note of yours" in out and "approved (no tests" in out, out[-600:]
    assert json.loads(machine.succeed(f"cat {home}/.local/state/workers/alpha/approvals/b1/lk4"))["note"] == "From a terminal."
    machine.fail("pgrep -x less")

with subtest("R5 of the review: a filter in the settings of the worker's copy does not change the code that is tested"):
    worker = lambda name, script, branch="b1": start(f"--branch {branch} --name {name}", script, project="~/tested", locked=True)
    # Control: the committed code is broken, and the run says so
    out = machine.succeed(worker("ta", "echo 'echo 6' > src/sum.sh; git -c user.name=t -c user.email=t@t commit -q -a -m broken; queue acceptance; echo \"exit=$?\"") + " 2>/dev/null")
    assert out.split()[-1] == "exit=1" and "FAIL t-sum" in out, out
    # The worker names a filter for that file in a committed .gitattributes, and gives the filter a program in the settings of its
    # copy, which are in no commit: the program prints the working code
    plant = (
        "printf '%s\\n' \"echo 'echo \\$((\\$1 + \\$2))'\" > $WORKER_SCRATCH/plant.sh;"
        " echo 'src/sum.sh filter=plant' > .gitattributes; git add -A; git -c user.name=t -c user.email=t@t commit -q -m attributes;"
        " git config filter.plant.smudge \"bash $WORKER_SCRATCH/plant.sh\"; git config filter.plant.clean cat;"
        " echo \"committed: $(git cat-file -p HEAD:src/sum.sh)\"; queue acceptance; echo \"exit=$?\""
    )
    out = machine.succeed(worker("ta", plant) + " 2>/dev/null")
    print("R5:", out.replace("\n", " | "))
    assert "committed: echo 6" in out, out
    assert "FAIL t-sum" in out and out.split()[-1] == "exit=1", "the run passed although the committed code is broken: " + out
    # The same for an object that the copy's settings put in another's place (git replace): the commit is what is tested
    replace = (
        "git config --unset filter.plant.smudge; good=$(printf 'echo $(($1 + $2))\\n' | git hash-object -w --stdin);"
        " git replace $(git rev-parse HEAD:src/sum.sh) $good; echo \"as the copy shows it: $(git cat-file -p HEAD:src/sum.sh)\"; queue acceptance; echo \"exit=$?\""
    )
    out = machine.succeed(worker("ta", replace) + " 2>/dev/null")
    print("R5, a replaced object:", out.replace("\n", " | "))
    assert "as the copy shows it: echo $(($1 + $2))" in out and "FAIL t-sum" in out and out.split()[-1] == "exit=1", out

with subtest("The status (W10 to W14, W17): one document, in which every value says where it comes from"):
    status = lambda: json.loads(machine.succeed(asUser("workers status --json")))
    find = lambda document, name, project="tested": [entry for entry in document["workers"] if (entry["project"], entry["name"]) == (project, name)][0]
    worker = lambda name, script: start(f"--branch b1 --name {name}", script, project="~/tested", locked=True)
    reviewer = lambda script: start("--role reviewer --branch b1 --name tr --of ta", script, project="~/tested")
    groups = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/workers.slice"
    kinds = {"measured", "recorded", "derived", "self-reported", "claimed"}
    # The dashboard's own reader, which the start script of this check passes on (W13)
    watch = watchProgram

    def accepted(document):
        """The dashboard's own word on a document: its status and what it said"""
        machine.succeed("cat > /tmp/status.json <<'END-OF-THE-DOCUMENT'\n" + json.dumps(document) + "\nEND-OF-THE-DOCUMENT")
        return machine.execute(f"{watch} --validate --file /tmp/status.json 2>&1")

    def walk(value, path="document"):
        """Every value of the document with its place; no null anywhere, every text valid and at most 4096 bytes"""
        assert value is not None, f"{path} is null"
        if isinstance(value, dict):
            assert ("source" not in value) or (value["source"] in kinds), f"{path}.source is {value['source']}"
            for key, inner in value.items():
                walk(inner, f"{path}.{key}")
        elif isinstance(value, list):
            for index, inner in enumerate(value):
                walk(inner, f"{path}[{index}]")
        elif isinstance(value, str):
            assert len(value.encode()) <= 4096, f"{path} is {len(value.encode())} bytes"

    ## W14 first, since it needs the reviewer's start: a review of the implementer's commit as it is, then a new commit
    machine.succeed(reviewer("echo 'needs changes: the sum is wrong' > review.md"))
    reviews = find(status(), "ta")["reviews"]
    print("W14, before the commit:", reviews)
    assert reviews == {"count": 1, "outdated": 0, "verdicts": [{"by": "tr", "value": "needs changes: the sum is wrong", "source": "claimed"}], "source": "derived"}, reviews
    machine.succeed(worker("ta", "echo more > more && git add more && git -c user.name=t -c user.email=t@t commit -q -m more"))
    document = status()
    assert (find(document, "ta")["reviews"]["count"], find(document, "ta")["reviews"]["outdated"]) == (1, 1), find(document, "ta")["reviews"]
    # Control: the reviewer started again reviews the new commit
    machine.succeed(reviewer("true"))
    assert find(status(), "ta")["reviews"]["outdated"] == 0

    ## W10: the worker writes "passed" where it writes its own word; its recorded run of the approved tests failed
    machine.succeed(worker("ta", "queue acceptance > /dev/null; echo 'passed: all tests pass, ready to merge' > ../reports/status.md"))
    ta = find(status(), "ta")
    print("W10:", {key: ta[key] for key in ("acceptance", "claim", "state", "intent", "commits", "lastQueuedRun")})
    assert ta["acceptance"]["value"] == "failed" and ta["acceptance"]["source"] == "recorded" and ta["acceptance"]["onCurrentCommit"] is True, ta["acceptance"]
    assert ta["claim"] == {"value": "passed: all tests pass, ready to merge", "source": "claimed"}, ta["claim"]
    # Nowhere but in the claim does the document say "passed" of this worker
    assert "passed" not in json.dumps({key: value for key, value in ta.items() if key != "claim"}), ta
    assert ta["intent"]["approved"] is True and ta["intent"]["approach"] == 2 and ta["intent"]["changedSinceApproval"] is False and ta["lastQueuedRun"]["exit"] == 1, ta
    assert ta["commits"]["ahead"] >= 4 and ta["commits"]["behind"] == 0 and ta["commits"]["source"] == "derived" and ta["commits"]["uncommitted"]["source"] == "self-reported", ta["commits"]
    # Control: after a correction that is committed, and a run, the recorded value is "passed"; one more commit makes it "stale"
    machine.succeed(worker("ta", "git rm -q --cached .gitattributes; rm .gitattributes; git replace -d $(git rev-parse HEAD:src/sum.sh) > /dev/null; echo 'echo $(($1 + $2))' > src/sum.sh; git -c user.name=t -c user.email=t@t commit -q -a -m right; queue acceptance > /dev/null"))
    assert find(status(), "ta")["acceptance"] == {"value": "passed", "onCurrentCommit": True, "time": find(status(), "ta")["acceptance"]["time"], "source": "recorded"}
    machine.succeed(worker("ta", "echo again >> more && git -c user.name=t -c user.email=t@t commit -q -a -m again"))
    assert find(status(), "ta")["acceptance"]["value"] == "stale"
    # A worker that is not approved, one without tests, and the roles without a lock
    document = status()
    assert find(document, "td")["state"] == {"value": "planned", "source": "derived"} and find(document, "td")["intent"] == {"approved": False, "source": "recorded"}
    assert find(document, "td")["acceptance"] == {"value": "never run", "source": "recorded"}
    assert find(document, "tr")["state"]["value"] == "idle" and "intent" not in find(document, "tr") and find(document, "tr")["role"] == "reviewer"

    ## W17: the agent's to-do list, from the last entry of the to-do extension in the worker's newest session file
    def session(text):
        machine.succeed(
            "cat > /tmp/session <<'END-OF-THE-SESSION'\n" + text + "END-OF-THE-SESSION",
            asUser(f"mkdir -p {folders}/tested/b1/ta/sessions/--sample--"),
            f"install -o {user} -m 600 /tmp/session {folders}/tested/b1/ta/sessions/--sample--/session.jsonl",
        )

    session(sampleSession)
    steps = find(status(), "ta")["steps"]
    print("W17:", steps)
    assert steps == {
        "done": 1,
        "total": 3,
        "source": "claimed",
        "current": "Adding the boundary term",
        "changed": calendar.timegm(time.strptime("2026-11-14T10:05:00", "%Y-%m-%dT%H:%M:%S")),
        "items": [
            {"text": "Read the residual assembly", "state": "done"},
            {"text": "Add the boundary term to the residual", "state": "in work"},
            {"text": "Extend the test of the residual", "state": "open"},
        ],
    }, steps
    # The same entries in a form that this tool does not know (a task's text under another name): no list, and a message
    session(sampleSession.replace('"subject"', '"title"'))
    status_, out = machine.execute(asUser("workers status --json 2>&1 > /tmp/changed.json"))
    assert status_ == 0 and "the to-do list of tested/b1/ta is not in the form that this tool knows of the to-do extension: it is left out" in out, out
    assert "steps" not in find(json.loads(machine.succeed("cat /tmp/changed.json")), "ta")
    session(sampleSession)

    ## W11 and W13: an implementer that runs a job, a reviewer, a manager and an ordinary session, as the dashboard's reader takes it
    # (the job and the ordinary session say when they run, and wait at a gate until the document is judged)
    held = "touch $WORKER_SCRATCH/w11-runs; " + gate("w11-go")
    machine.succeed(f"({worker('ta', f'queue run -- bash -c {shlex.quote(held)}')}) > /dev/null 2>&1 & ({start('', held, project='~/tested')}) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/tested/b1/ta/w11-runs && ls {areas}/tested-*/plain/session/w11-runs", timeout=30 * pace)
    status()
    # (a share of the processors is what was used between two looks: two seconds of it)
    machine.sleep(2)
    document = status()
    agent = f"{groups}/workers-agents.slice/worker:tested:b1:ta.scope"
    measured = [int(value) for value in machine.succeed(f"cat {agent}/memory.current {agent}/memory.max {groups}/memory.max {groups}/workers-agents.slice/memory.max {groups}/memory.current {groups}/workers-agents.slice/cpu.max").split()]
    ta = find(document, "ta")
    print("W11, the machine:", document["machine"], "| the implementer:", {key: ta[key] for key in ("running", "memory", "cpu", "jobs", "state", "lastRun")})
    walk(document)
    assert document["version"] == 1 and abs(document["generated"] - int(machine.succeed("date +%s"))) < 30
    assert set(document["machine"]) == {"memory", "agentsMemory", "agentsCpu", "memoryStops", "cpus", "queue"}, set(document["machine"])
    names = [(entry["project"], entry["branch"], entry["name"]) for entry in document["workers"]]
    assert len(names) == len(set(names)) and {entry["role"] for entry in document["workers"]} == {"implementer", "reviewer", "deep-reviewer", "manager", "plain"}, names
    for entry in document["workers"]:
        assert isinstance(entry["running"]["value"], bool) and entry["state"]["value"] in ("planned", "approved", "implementing", "ready for review", "reviewed", "merged", "removable", "idle"), entry
    # Measured values against the resource groups' own files: the limits exactly, what is used within a quarter or 4 MiB
    assert ta["memory"]["limit"] == measured[1] == 536870912 and document["machine"]["memory"]["limit"] == measured[2] == 1073741824 and document["machine"]["agentsMemory"]["limit"] == measured[3], (ta["memory"], measured)
    assert abs(ta["memory"]["used"] - measured[0]) <= max(measured[0] // 4, 4 << 20) and abs(document["machine"]["memory"]["used"] - measured[4]) <= max(measured[4] // 4, 4 << 20), (ta["memory"], document["machine"]["memory"], measured)
    # (an earlier subtest set the agents' share of the processors to 250% until the next restart)
    assert document["machine"]["agentsCpu"]["limit"] == measured[5] / measured[6] == 2.5 and 0 <= document["machine"]["agentsCpu"]["share"] < 2.5 and document["machine"]["cpus"]["timingReserved"] is False, document["machine"]["agentsCpu"]
    assert document["machine"]["queue"] == {"slots": {"taken": 1, "total": 5}, "parallel": {"taken": 0, "total": 1}, "timing": {"taken": 0, "total": 1}, "exclusive": False, "waiting": 0}, document["machine"]["queue"]
    # The running job, and the ordinary session as a worker of the role "plain"
    assert ta["running"]["value"] is True and abs(ta["running"]["since"] - document["generated"]) < 60 and ta["lastRun"] == ta["running"]["since"], ta["running"]
    assert len(ta["jobs"]) == 1 and (ta["jobs"][0]["mode"], ta["jobs"][0]["state"], ta["jobs"][0]["command"]) == ("run", "running", "bash -c " + held) and ta["jobs"][0]["memory"]["used"] > 0, ta["jobs"]
    plain = [entry for entry in document["workers"] if entry["role"] == "plain"]
    assert len(plain) == 1 and plain[0]["project"].startswith("tested-") and plain[0]["running"] == {"value": True} and plain[0]["memory"]["limit"] == 536870912, plain
    assert find(document, "tr")["running"]["value"] is False and "memory" not in find(document, "tr")
    # W13: the dashboard's reader accepts the document as it is. Control: it refuses one with a null, so it does judge
    assert accepted(document) == (0, ""), accepted(document)
    broken = json.loads(json.dumps(document))
    broken["workers"][0]["state"]["value"] = None
    assert accepted(broken)[0] == 1, accepted(broken)
    # The table for a terminal, from the same values
    out = machine.succeed(asUser("workers status"))
    print("the table:", out)
    assert "tested/b1/ta" in out and "stale" in out and "passed: all tests pass, ready to merge" in out and "CLAIMED BY THE AGENT" in out, out
    machine.succeed(f"for area in {areas}/tested/b1/ta {areas}/tested-*/plain/session; do touch $area/w11-go; done")
    sandboxEnded("tested/b1/ta")
    machine.wait_until_succeeds(asUser("! systemctl --user list-units --plain --no-legend 'pi-tested-*.scope' | grep -q ."), timeout=30 * pace)

    ## W12: an agent's text in every place that the status reads
    # For printf: an escape sequence that sets the terminal's title, one that clears the screen, a direction override, two bytes
    # that are no text, and 9000 letters. The second is the same as JSON writes it, the third as a shell takes it between $'...'
    nasty = "\\033]0;a title\\007\\033[2J\\342\\200\\256 reversed \\377\\376 not UTF-8 " + "x" * 9000
    nastyJson = "\\\\u001b]0;a title\\\\u0007\\\\u001b[2J\\\\u202e reversed " + "x" * 9000
    nastyWords = "\\033]0;a title\\007\\033[2J\\342\\200\\256 reversed " + "x" * 9000
    hostile = (
        # The agent's own word, and a reviewer's verdict: escape sequences, a direction override, bytes that are no text, a megabyte in one line
        f"printf '{nasty}' > ../reports/status.md; head -c 1M /dev/zero | tr '\\0' y >> ../reports/status.md;"
        # The form: a link to a file that the worker does not see
        f" rm ../reports/intent.md; ln -s {home}/.ssh/id_test ../reports/intent.md;"
        # The session file: 200 MiB, then an entry nested deeper than a reader goes, then a list whose texts are as above
        " mkdir -p ~/.pi/agent/sessions/--hostile-- && cd ~/.pi/agent/sessions/--hostile-- && truncate -s 200M huge.jsonl"
        " && { echo; printf '{\"type\": \"custom\", \"customType\": \"rpiv-todo-state\", \"data\": '; head -c 200000 /dev/zero | tr '\\0' '['; echo;"
        f" printf '{{\"type\": \"custom\", \"customType\": \"rpiv-todo-state\", \"data\": {{\"tasks\": [{{\"id\": 1, \"subject\": \"{nastyJson}\", \"status\": \"in_progress\"}}], \"nextId\": 2}}}}\\n'; }} >> huge.jsonl"
    )
    machine.succeed(worker("ta", hostile) + " 2>/dev/null", reviewer(f"printf '{nasty}\\nsecond line\\n' > review.md"))
    # A job whose command line holds the same, while the status is asked; and the time the call takes
    machine.succeed(f"({worker('ta', 'queue run -- bash -c $' + chr(39) + f'sleep {8 * pace}; : ' + nastyWords + chr(39))}) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(f"pgrep -x -f 'sleep {8 * pace}' > /dev/null", timeout=30 * pace)
    begun = time.time()
    document = status()
    took = time.time() - begun
    ta = find(document, "ta")
    print(f"W12: the call took {took:.1f} s;", json.dumps({key: ta.get(key) for key in ("claim", "steps", "intent", "jobs", "reviews")})[:1500])
    walk(document)
    # (an emulated machine takes many times as long for everything; there the bound only says that the call ends)
    assert took < (120 if emulated else 10), took
    # Each text is there, cut; nothing was read through the link; the list is the last whole entry's
    assert ta["claim"]["value"].startswith("\x1b]0;a title\x07\x1b[2J\u202e reversed \ufffd\ufffd not UTF-8 xxx") and len(ta["claim"]["value"].encode()) == 4096, ta["claim"]
    assert ta["intent"]["changedSinceApproval"] is True and "secret" not in json.dumps(document), ta["intent"]
    assert ta["steps"]["total"] == 1 and ta["steps"]["items"][0]["text"].startswith("\x1b]0;a title\x07\x1b[2J\u202e reversed xxx") and len(ta["steps"]["items"][0]["text"].encode()) == 4096, ta["steps"]
    assert ta["steps"]["current"] == ta["steps"]["items"][0]["text"]
    assert ta["reviews"]["verdicts"][0]["value"].startswith("\x1b]0;a title") and "second line" not in ta["reviews"]["verdicts"][0]["value"], ta["reviews"]
    assert ta["jobs"][0]["command"].startswith(f"bash -c sleep {8 * pace}; : \x1b]0;a title\x07\x1b[2J\u202e reversed xxx") and len(ta["jobs"][0]["command"].encode()) == 4096, ta["jobs"]
    # The dashboard's reader accepts this document too
    assert accepted(document) == (0, ""), accepted(document)
    machine.wait_until_fails(f"pgrep -x -f 'sleep {8 * pace}'", timeout=40 * pace)
    sandboxEnded("tested/b1/ta")

    ## `workers take` says what the manager's records hold about the whole suite on the commit it brings, and goes on
    manager = lambda script: start("--role manager", script, project="~/tested")
    commit = "git -c user.name=t -c user.email=t@t commit -q"
    for change, expected in [
        ("echo note > note && git add note", "no run of the project's whole suite is recorded for this commit of the manager's copy"),
        ("queue acceptance --all > /dev/null", "the project's whole suite passed on this commit of the manager's copy (recorded "),
        ("echo 'echo 6' > src/sum.sh && git add src/sum.sh && " + commit + " -m broken && { queue acceptance --all > /dev/null; true; }", "the project's whole suite FAILED on this commit of the manager's copy (recorded "),
    ]:
        machine.succeed(manager(f"git checkout -q main && {change} && {{ git diff --cached --quiet || {commit} -m change; }}"))
        out = machine.succeed(asUser("cd ~/tested && workers take && git reset -q --hard") + " 2>&1")
        assert expected in out and "staged and not committed" in out, f"{expected}: {out[-500:]}"


# R6 to R9 are the reviewer's tests of part 3 (REVIEW-WORKFLOW-3.md), with the reviewer's own judgements
with subtest("R6 of the review: the approved tests are judged on the commit of the worker's own branch, the one that reviewers and the manager take"):
    worker = lambda name, script: start(f"--branch b1 --name {name}", script, project="~/tested", locked=True)
    commit = "git -c user.name=t -c user.email=t@t commit -q"
    copy = f"{folders}/tested/b1/tz/repo"
    mirror = f"{home}/.local/state/workers/tested/mirror.git"
    remote = lambda reference: machine.succeed(asUser(f"git ls-remote file://{copy} {reference}")).split()[0]
    machine.succeed(worker("tz", "true") + " 2>/dev/null")
    form("tz", "- `t-sum`: the sum is what changes\n")
    machine.succeed(worker("tz", "queue acceptance") + " 2>/dev/null")
    machine.succeed(approve("tested/b1/tz", ["2", "", "yes"]))
    out = machine.succeed(worker("tz", f"echo 'echo 6' > src/sum.sh; {commit} -a -m broken; git checkout -q --detach HEAD~1; queue acceptance; echo \"exit=$?\"") + " 2>/dev/null")
    tz = find(status(), "tz")
    tip, head = remote("refs/heads/worker/b1/tz"), remote("HEAD")
    print("R6-RESULT", out.split(), {"branch": tip[:8], "HEAD": head[:8], "acceptance": tz["acceptance"], "state": tz["state"]})
    # Control: the same tests on the branch's own commit
    control = machine.succeed(worker("tz", "git checkout -q worker/b1/tz; queue acceptance; echo \"exit=$?\"") + " 2>/dev/null")
    print("R6-CONTROL", control.split())
    assert tip != head and control.split()[-1] == "exit=1", (tip, head, control)
    assert tz["acceptance"]["value"] != "passed", "R6: the status says 'passed' while the branch that reviewers and the manager take holds a commit on which the approved tests fail"


with subtest("R9 of the review: a reviewer that has only been started has not reviewed"):
    machine.succeed(start("--role reviewer --branch b1 --name ty --of tz", "true", project="~/tested") + " 2>/dev/null")
    tz = find(status(), "tz")
    print("R9-RESULT", {"state": tz["state"], "reviews": tz["reviews"]})
    assert tz["state"]["value"] != "reviewed", "R9: the state is 'reviewed' although the reviewer has written no review"


with subtest("R8 of the review: an answer that could not be made is not kept"):
    # A fetch that fails once (here: the reference is locked, as while another call writes it)
    before = find(status(), "tz")["commits"]
    machine.succeed(worker("tz", f"echo more >> notes; git add notes; {commit} -m more") + " 2>/dev/null")
    lock = f"{mirror}/refs/copies/b1/tz/worker/b1/tz.lock"
    machine.succeed(asUser(f"mkdir -p $(dirname {lock}) && touch {lock}"))
    during = find(status(), "tz")["commits"]
    machine.succeed(asUser(f"rm {lock}"))
    after = find(status(), "tz")["commits"]
    again = find(status(), "tz")["commits"]
    print("R8-RESULT", {"before": before, "during the lock": during, "after it": after, "once more": again})
    assert ("ahead" in after) and ("ahead" in again), "R8: after one failed fetch the commits' counts stay away although the cause is gone"
    # Control of the case itself: during the lock there was no answer
    assert "ahead" not in during, during


with subtest("Status calls at the same moment: every one answers with the counts, and the tools' own repository is whole afterwards"):
    # Six calls, after a new commit that each of them has to fetch
    after = find(status(), "tz")["commits"]
    machine.succeed(worker("tz", f"echo again >> notes; {commit} -a -m again") + " 2>/dev/null")
    machine.succeed(asUser("cd /tmp && rm -f together-*; for n in 1 2 3 4 5 6; do (workers status --json > together-$n.json 2> together-$n.err; echo $? > together-$n.status) & done; wait"))
    together = [(machine.succeed(f"cat /tmp/together-{n}.status").strip(), machine.succeed(f"cat /tmp/together-{n}.err").strip(), find(json.loads(machine.succeed(f"cat /tmp/together-{n}.json")), "tz")["commits"]) for n in range(1, 7)]
    print("R8, six calls at once:", together)
    assert all(result == "0" and errors == "" and counts.get("ahead") == after["ahead"] + 1 for result, errors, counts in together), together
    machine.succeed(asUser(f"git --git-dir {mirror} fsck --connectivity-only 2>&1"))


with subtest("R7 of the review: the tools' own repository does not keep what a worker dropped"):
    size = lambda path: int(machine.succeed(f"du -sm {path}").split()[0])
    for round in range(4):
        machine.succeed(worker("tz", f"head -c 30M /dev/urandom > blob; git add blob; {commit} --amend -m blob; git reflog expire --expire=now --all; git gc -q --prune=now") + " 2>/dev/null")
        status()
    sizes = {"the copy's .git (MiB)": size(copy + "/.git"), "the tools' own repository in ~/.local/state (MiB)": size(mirror)}
    print("R7-RESULT", sizes)
    assert sizes["the tools' own repository in ~/.local/state (MiB)"] <= 2 * sizes["the copy's .git (MiB)"], "R7: the tools' own repository keeps what the worker dropped, outside every limit of the worker"
    # Control: the counts are still made after the tidying
    assert find(status(), "tz")["commits"]["ahead"] >= 1


with subtest("W15: an implementer reads the reports of the reviewers that were started against it, from its next start, and cannot write them"):
    review = f"{folders}/tested/b1/tx/reports/review.md"
    look = f'cat {review} 2>&1; echo "read=$?"; echo x >> {review} 2>/dev/null; echo "write=$?"; touch {folders}/tested/b1/tx/reports/new 2>/dev/null; echo "new=$?"; ls {folders}/tested/b1'
    # The implementer runs while a new reviewer is started against it and writes: this sandbox was built before, and does not have the report
    machine.succeed(f"({worker('tz', 'echo sandbox-runs; ' + gate('w15-go') + '; ' + look)}) > /tmp/w15 2>&1 &")
    machine.wait_until_succeeds("grep -q sandbox-runs /tmp/w15", timeout=30 * pace)
    machine.succeed(start("--role reviewer --branch b1 --name tx --of tz", "echo 'needs changes: the sum is wrong' > review.md", project="~/tested") + " 2>/dev/null")
    openGate("tested/b1/tz", "w15-go")
    sandboxEnded("tested/b1/tz")
    out = machine.succeed("cat /tmp/w15")
    print("W15, the implementer that ran meanwhile:", out)
    assert "read=1" in out and "needs changes" not in out, out
    # Its next start: readable, not writable
    out = machine.succeed(worker("tz", look) + " 2>/dev/null")
    print("W15, at its next start:", out)
    # (it has the folders of both reviewers that were started against it, and its own)
    assert out.splitlines()[:4] == ["needs changes: the sum is wrong", "read=0", "write=1", "new=1"] and out.split()[-3:] == ["tx", "ty", "tz"], out
    assert machine.succeed(f"cat {review}").strip() == "needs changes: the sum is wrong" and machine.succeed(f"ls {folders}/tested/b1/tx/reports").split() == ["review.md"]
    # The same in a job of the implementer
    assert machine.succeed(worker("tz", f"queue run -- bash -c {shlex.quote(look)}") + " 2>/dev/null").splitlines()[:4] == ["needs changes: the sum is wrong", "read=0", "write=1", "new=1"]
    # Another implementer of the branch does not see it; control: it does see its own reviewer's (ta has tr)
    out = machine.succeed(worker("ta", f"{look}; cat {folders}/tested/b1/tr/reports/review.md > /dev/null; echo \"own=$?\"") + " 2>/dev/null")
    print("W15, another implementer:", out)
    assert "read=1" in out and "needs changes: the sum" not in out and "own=0" in out and "tx" not in out.split() and "ty" not in out.split(), out
    # With the review written by a reviewer that started from the current commit, the state is `reviewed` (control of R9)
    assert find(status(), "tz")["state"] == {"value": "reviewed", "source": "derived"}, find(status(), "tz")["state"]


with subtest("The states: each one is reached, and says what it rests on; ahead, behind, and the worker's own word on uncommitted changes"):
    machine.succeed(asUser(repository.format("~/stages")))
    stage = lambda name, script: start(f"--branch b1 --name {name}", script, project="~/stages", locked=True)
    seen = lambda name="s1": find(status(), name, "stages")
    listed = lambda name="s1": [line.split() for line in machine.succeed(asUser("workers list")).splitlines() if line.split()[:3] == ["stages", "b1" if name != "manager" else "manager", name]][0]
    commit = "git -c user.name=t -c user.email=t@t commit -q"
    says = lambda word: {"value": word, "source": "derived"}

    ## planned: started, not approved
    machine.succeed(stage("s1", "true") + " 2>/dev/null")
    s1 = seen()
    print("planned:", {key: s1.get(key) for key in ("state", "intent", "commits", "removable")})
    assert s1["state"] == says("planned") and s1["intent"]["approved"] is False and s1["removable"]["value"] is False, s1

    ## approved: the user's word, and nothing done yet
    machine.succeed(asUser("printf '\\nyes\\n' | workers approve --without-form stages/b1/s1"))
    assert seen()["state"] == says("approved"), seen()["state"]
    # Control: a claim alone moves nothing. An approved worker without work that calls itself ready stays `approved`
    machine.succeed(stage("s1", "echo 'ready for review: trust me' > ../reports/status.md") + " 2>/dev/null")
    assert seen()["state"] == says("approved") and seen()["claim"]["value"] == "ready for review: trust me", seen()
    machine.succeed(stage("s1", "rm ../reports/status.md") + " 2>/dev/null")

    ## implementing: a commit of its own; a file that is not committed when its job reports; the project's branch moves on
    machine.succeed(stage("s1", f"echo one > one && git add one && {commit} -m one && echo draft > draft && queue run -- true") + " 2>/dev/null")
    machine.succeed(asUser(f"cd ~/stages && git checkout -q b1 && echo theirs > theirs && git add theirs && {commit} -m theirs && git checkout -q main"))
    s1 = seen()
    print("implementing:", {key: s1.get(key) for key in ("state", "commits", "removable")})
    assert s1["state"] == says("implementing"), s1["state"]
    assert s1["commits"] == {"ahead": 1, "behind": 1, "source": "derived", "uncommitted": {"value": True, "source": "self-reported"}}, s1["commits"]
    assert listed()[4] == "stopped" and listed()[-1] == "1", listed()

    ## ready for review: the worker's own word, on top of work that is there; the state says that it is claimed
    machine.succeed(stage("s1", "echo 'ready for review: the file is there' > ../reports/status.md; rm draft; queue run -- true") + " 2>/dev/null")
    s1 = seen()
    assert s1["state"] == {"value": "ready for review", "source": "claimed"} and s1["commits"]["uncommitted"] == {"value": False, "source": "self-reported"}, s1
    # `workers status` says how its next reviewer is started, under a name that is free
    out = machine.succeed(asUser("workers status"))
    print("the table, with the reviewer's start:", out[-700:])
    assert f"to start the next reviewer of stages/b1/s1 (the manager writes its task file first: {folders}/stages/instructions/b1/s1-r1.md):\n  cd {home}/stages && pi --role reviewer --branch b1 --name s1-r1 --of s1" in out, out
    assert "next reviewer of tested/b1/tz" not in out, out

    ## reviewed: a reviewer that started from this commit has written its review; started alone, it has not (R9)
    machine.succeed(start("--role reviewer --branch b1 --name s1-r1 --of s1", "true", project="~/stages") + " 2>/dev/null")
    assert seen()["state"]["value"] == "ready for review", seen()["state"]
    machine.succeed(start("--role reviewer --branch b1 --name s1-r1 --of s1", "echo accepted > review.md", project="~/stages") + " 2>/dev/null")
    s1 = seen()
    assert s1["state"] == says("reviewed") and s1["reviews"]["verdicts"] == [{"by": "s1-r1", "value": "accepted", "source": "claimed"}], s1
    # (the name is taken now: the next reviewer's would be s1-r2; none is proposed for work that is reviewed)
    assert "next reviewer of stages/b1/s1" not in machine.succeed(asUser("workers status"))

    ## merged: a manager's copy holds every commit of it; here it has a file again that is not committed, so it is not removable
    machine.succeed(start("--role manager", f"git fetch -q {folders}/stages/b1/s1/repo worker/b1/s1:refs/workers/b1/s1 && git checkout -q b1 && git -c user.name=t -c user.email=t@t merge -q --no-edit refs/workers/b1/s1", project="~/stages") + " 2>/dev/null")
    machine.succeed(stage("s1", "echo draft > draft; queue run -- true") + " 2>/dev/null")
    s1 = seen()
    print("merged:", {key: s1.get(key) for key in ("state", "commits", "removable")}, listed())
    assert s1["state"] == says("merged") and s1["removable"] == {"value": False, "source": "derived"} and listed()[4] == "stopped" and listed()[-1] == "0", (s1, listed())

    ## removable: merged, its last word is that nothing is uncommitted, and it does not run
    machine.succeed(f"({stage('s1', 'rm draft; queue run -- true; echo sandbox-runs; ' + gate('stages-go'))}) > /tmp/stages 2>&1 &")
    machine.wait_until_succeeds("grep -q sandbox-runs /tmp/stages", timeout=30 * pace)
    s1 = seen()
    assert s1["state"] == says("merged") and s1["removable"]["value"] is False and s1["running"]["value"] is True, s1
    openGate("stages/b1/s1", "stages-go")
    sandboxEnded("stages/b1/s1")
    s1 = seen()
    print("removable:", {key: s1.get(key) for key in ("state", "commits", "removable")}, listed())
    assert s1["state"] == says("removable") and s1["removable"] == {"value": True, "source": "derived"} and listed()[4] == "removable", (s1, listed())
    # The reminder's sentence (on this machine the folders are no datasets, so it names no size)
    out = machine.succeed(asUser("workers status --reminder"))
    print("the reminder:", out)
    count = sum(1 for entry in status()["workers"] if entry.get("removable", {}).get("value"))
    assert count >= 1 and out.startswith(f"{count} worker(s) can be removed") and "workers remove --merged stages" in out and "GiB" not in out, out
    # `workers remove --merged` is today's removal: on a machine with plain folders it is refused as that is
    assert "plain folders on this machine" in machine.fail(asUser("workers remove --merged stages") + " 2>&1")
    assert "has no workers" in machine.fail(asUser("workers remove --merged nothing") + " 2>&1")


with subtest("A manager's own commits are its own: they are not counted as held by 'a manager's copy' because the tools fetched that copy before"):
    # The manager of this project made commits on its main branch which the user took and did not commit: nobody else holds them
    row = [line.split() for line in machine.succeed(asUser("workers list")).splitlines() if line.split()[:3] == ["tested", "manager", "manager"]][0]
    print("the manager's row:", row)
    assert row[3] == "manager" and row[-1].isdigit() and int(row[-1]) >= 1, row
    out = machine.fail(asUser("workers remove tested/manager/manager") + " 2>&1")
    assert f"has {row[-1]} commit(s) that neither the project nor a manager's copy holds" in out, out
    # Control: an implementer whose commits the manager's copy holds is counted as before
    assert [line.split() for line in machine.succeed(asUser("workers list")).splitlines() if line.split()[:3] == ["stages", "b1", "s1"]][0][-1] == "0"
