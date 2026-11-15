import json
import shlex
import time

home = f"/home/{user}"
folders = f"{home}/workers"
areas = f"{home}/scratch/workers"
cgroup = "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service"


def asUser(command):
    """Run a command as the user, outside any sandbox"""
    environment = f"HOME={home} USER={user} XDG_RUNTIME_DIR=/run/user/1000 PATH=/run/wrappers/bin:/run/current-system/sw/bin"
    # Its input is closed off: sudo forwards its input to the command, and here that input is the channel of the test driver's own commands
    return f"sudo -u {user} env -i {environment} bash -c {shlex.quote(command)} < /dev/null"


def approved(project, branch, name):
    """The user's word that opens an implementer's copy without a written intent, given once: the tests of the lock are in workers-roles"""
    record = f"~/.local/state/workers/{project}/approvals/{branch}/{name}"
    return f"[ -e {record} ] || printf '\\nyes\\n' | workers approve --without-form {project}/{branch}/{name} > /dev/null 2>&1; "


def worker(name, script, project="alpha"):
    """Run a script in the sandbox of an implementer of branch b1"""
    return asUser(approved(project, "b1", name) + f"cd ~/{project} && worker-shell --branch b1 --name {name} -c {shlex.quote(script)}")


def plainSession(script, project="gamma"):
    """Run a script in a sandbox without worker options"""
    return asUser(f"cd ~/{project} && worker-shell -c {shlex.quote(script)}")


def background(command, log):
    machine.succeed(f"({command}) > {log} 2>&1 &")


def slot(name="slot1"):
    return machine.succeed(f"if flock -n /run/worker-queue/{name} true; then echo free; else echo taken; fi").strip()


def running(pattern):
    """Whether a process with exactly this command line exists, seen from outside every sandbox"""
    return machine.execute(f"pgrep -x -f {shlex.quote(pattern)}")[0] == 0


def userUnits(pattern):
    return machine.succeed(asUser(f"systemctl --user list-units --plain --no-legend --all {pattern} | awk '{{ print $1 }}'")).split()


def record(name, project="alpha"):
    return json.loads(machine.succeed(f"tail -n 1 {folders}/{project}/b1/{name}/records/runs.jsonl"))


def loop(tag):
    # (the loops outlast the subtest that uses them, which ends them itself)
    return f"timeout 3600 bash -c 'while :; do :; done' {tag}"


def allowed(tag):
    """The CPUs a busy loop may use, and the CPU it runs on now"""
    pid = machine.succeed(f"pgrep -x -f 'bash -c while :; do :; done {tag}'").split()[0]
    return machine.succeed(f"grep Cpus_allowed_list /proc/{pid}/status | cut -f2; cut -d' ' -f39 /proc/{pid}/stat").split()


def boot():
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("user@1000.service")


def gate(name):
    """Inside a sandbox or a job: wait here until the test lets it go on, with openGate()"""
    return f'until [ -e "$WORKER_SCRATCH/{name}" ]; do sleep 0.2; done'


def openGate(name, of="a", project="alpha"):
    machine.succeed(f"touch {areas}/{project}/b1/{of}/{name}")


def sandboxEnded(name, project="alpha", timeout=30):
    """Wait until the sandbox of a worker that was seen running has ended"""
    machine.wait_until_succeeds(asUser(f"! systemctl --user is-active --quiet worker:{project}:b1:{name}.scope"), timeout=timeout * pace)


def until(condition, timeout=20, required=True):
    """Wait for a condition that this test computes itself; with required=False the caller judges what it finds afterwards"""
    deadline = time.time() + timeout * pace
    while not condition():
        if (time.time() > deadline):
            assert not required, "the condition did not come about in time"
            return
        time.sleep(0.3)


def waiting():
    """How many requests wait for a slot, as the brokers say"""
    return json.loads(machine.succeed(asUser("workers status --json")))["machine"]["queue"]["waiting"]


machine.start()
boot()
# Inside a Nix build on a host without hardware virtualisation this machine is emulated, and many times slower. Nothing here
# waits a fixed time for another side to be ready: it waits for the condition, or the other side waits at a gate. What has to
# last, a job that another one must meet, lasts `pace` times as long on an emulated machine; and what is measured in seconds
# has more room there, while on a machine with hardware virtualisation every bound is as tight as it was
emulated = machine.succeed("systemd-detect-virt").strip() != "kvm"
pace = 10 if emulated else 1
print("emulated:", emulated, "pace:", pace)
machine.succeed(
    asUser(
        "mkdir -p ~/.ssh ~/alpha ~/beta ~/gamma && echo secret > ~/.ssh/id_test"
        " && for p in alpha beta gamma; do git -C ~/$p init -q -b main && git -C ~/$p -c user.name=t -c user.email=t@t commit -q --allow-empty -m base && git -C ~/$p branch b1; done"
        " && systemd-run --user --quiet --unit=desktop-standin --slice=app.slice sleep infinity"
    )
)
print("CONTROLLERS", machine.succeed(f"cat {cgroup}/cgroup.controllers"))
allocate = "python3 -c \"import time; x = b'x' * (%d << 20); time.sleep(%d); print('he' + 'ld')\""

with subtest("V1: two queued jobs from two sandboxes at once, one slot: they do not overlap; the record is the broker's"):
    # The machine has two slots; a third job holds one of them meanwhile, so that one is left
    background(worker("holder", f"queue run -- bash -c {shlex.quote(gate('v1-release'))}"), "/dev/null")
    until(lambda: slot("slot1") == "taken")
    assert slot("slot1") == "taken" and slot("slot2") == "free"
    job = f'echo ran; date +%s.%N > $WORKER_SCRATCH/start; sleep {3 * pace}; date +%s.%N > $WORKER_SCRATCH/end; exit 3'
    machine.succeed("(" + worker("a", f"queue run -- bash -c {shlex.quote(job)}; true") + " & " + worker("b", f"queue run -- bash -c {shlex.quote(job)}; true", "beta") + " & wait)")
    times = {}
    for project, name in [("alpha", "a"), ("beta", "b")]:
        times[name] = [float(machine.succeed(f"cat {areas}/{project}/b1/{name}/{point}")) for point in ("start", "end")]
    print("V1 intervals:", times)
    assert times["a"][1] <= times["b"][0] or times["b"][1] <= times["a"][0], f"the runs overlap: {times}"
    records = [record("a"), record("b", "beta")]
    print("V1 record:", records[0])
    assert max(entry["waited_s"] for entry in records) >= 2, records
    entry = records[0]
    assert entry["exit"] == 3 and entry["mode"] == "run" and entry["name"] == "a" and entry["branch"] == "b1" and entry["role"] == "implementer", entry
    assert entry["command"] == ["bash", "-c", job] and entry["folder"] == f"{folders}/alpha/b1/a/repo" and entry["start"].startswith("20"), entry
    machine.succeed(f"grep -qx ran {entry['output']}")
    # The commit is the one the copy is at, taken by the broker from outside; the worker's own word on changes is marked as such
    assert entry["commit"] == machine.succeed(asUser(f"git -C {folders}/alpha/b1/a/repo rev-parse HEAD")).strip() and entry["uncommitted_as_reported"] == "no", entry
    # The worker cannot change its records
    out = machine.succeed(worker("a", 'echo forged >> ../records/runs.jsonl; echo "append=$?"; rm ../records/runs.jsonl; echo "delete=$?"') + " 2>&1")
    assert "append=1" in out and "delete=1" in out, out
    # Control of the holder: it held its slot all the while
    assert slot("slot1") == "taken" or slot("slot2") == "taken"
    openGate("v1-release", "holder")
    sandboxEnded("holder")

with subtest("B7: one sandbox cannot hold every slot, and a run job without --parallel has one processor in this test"):
    def heldJob(marker, release):
        return f"touch $WORKER_SCRATCH/{marker}; {gate(release)}"

    first = heldJob("b7-first", "b7-release-first")
    second = heldJob("b7-second", "b7-release-second")
    fair = (
        f"queue run -- bash -c {shlex.quote(first)} & first=$!; queue run -- bash -c {shlex.quote(second)} & second=$!;"
        " until queue status | grep -q 'this sandbox: 2 of'; do sleep 0.2; done; touch $WORKER_SCRATCH/b7-ready; wait $first $second"
    )
    background(worker("fair", fair), "/tmp/b7-fair")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/fair/b7-ready", timeout=30 * pace)
    other = heldJob("b7-other", "b7-release-other")
    background(worker("other", f"queue run -- bash -c {shlex.quote(other)}"), "/tmp/b7-other")
    until(lambda: machine.execute(f"test -e {areas}/alpha/b1/other/b7-other")[0] == 0, timeout=3, required=False)
    otherStarted = machine.execute(f"test -e {areas}/alpha/b1/other/b7-other")[0] == 0
    fairStarted = len(machine.succeed(f"find {areas}/alpha/b1/fair -maxdepth 1 -name 'b7-first' -o -name 'b7-second'").split())
    print("B7 slots before release: fair", fairStarted, "other", otherStarted)
    openGate("b7-release-first", "fair")
    openGate("b7-release-second", "fair")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/other/b7-other", timeout=30 * pace)
    openGate("b7-release-other", "other")
    sandboxEnded("fair")
    sandboxEnded("other")

    def jobCores(name, option):
        body = "pids=''; for n in 1 2 3 4; do bash -c 'while :; do :; done' & pids=\"$pids $!\"; done; touch $WORKER_SCRATCH/b7-cpu-ready; " + gate("b7-cpu-release") + "; kill $pids; wait"
        background(worker(name, f"queue run {option} -- bash -c {shlex.quote(body)}"), f"/tmp/b7-{name}")
        machine.wait_until_succeeds(f"test -e {areas}/alpha/b1/{name}/b7-cpu-ready", timeout=30 * pace)
        unit = machine.succeed(asUser(f"systemctl --user list-units --plain --no-legend 'job-worker:alpha:b1:{name}-*.scope' | awk '{{ print $1 }}'")).strip()
        group = machine.succeed(asUser(f"systemctl --user show -p ControlGroup --value {unit}")).strip()
        usage = [int(machine.succeed(f"sleep {pause}; grep usage_usec /sys/fs/cgroup{group}/cpu.stat | cut -d' ' -f2")) for pause in (0, 8)]
        cores = (usage[1] - usage[0]) / 8e6
        openGate("b7-cpu-release", name)
        sandboxEnded(name)
        return cores

    ordinaryCores = jobCores("cpu", "")
    parallelCores = jobCores("cpupar", "--parallel")
    print("B7 processor use: ordinary", ordinaryCores, "parallel control", parallelCores)
    assert fairStarted == 1 and otherStarted, (fairStarted, otherStarted)
    assert 0.75 < ordinaryCores < 1.25, ordinaryCores
    assert parallelCores > 2.0, parallelCores

with subtest("The kept copy: output and errors stay apart for the agent, the kept file holds both, the exit status is the command's"):
    out = machine.succeed(worker("a", 'queue run -- bash -c "echo to-output; echo to-errors >&2; exit 5" > out 2> err; echo "status=$?"; echo "out: $(cat out)"; echo "err: $(cat err)"'))
    print("kept copy:", out, machine.succeed(f"cat {record('a')['output']}"))
    assert out.split("\n")[:3] == ["status=5", "out: to-output", "err: to-errors"], out
    assert sorted(machine.succeed(f"cat {record('a')['output']}").split()) == ["to-errors", "to-output"] and record("a")["exit"] == 5

with subtest("Every run has an id of its own, also the first runs of sessions that follow each other within a second"):
    for word in ["one", "two", "three", "four", "five", "six"]:
        machine.succeed(worker("ids", f"queue run -- echo {word}"))
    entries = [json.loads(line) for line in machine.succeed(f"cat {folders}/alpha/b1/ids/records/runs.jsonl").splitlines()]
    ended = [entry for entry in entries if "exit" in entry]
    print("run ids:", [entry["id"] for entry in ended])
    assert len(ended) == 6 and len({entry["id"] for entry in ended}) == 6, [entry["id"] for entry in ended]
    # Each kept file holds the output of its own run and nothing else
    assert [machine.succeed(f"cat {entry['output']}").strip() for entry in ended] == ["one", "two", "three", "four", "five", "six"]

with subtest("R4 of the review: a job's output arrives whole, in the stream and in the kept file, however slowly it is read at the end"):
    # Each case has a worker of its own, so that its scratch area holds the kept output of that one run
    kept = "cat $WORKER_SCRATCH/runs/*/output.log | wc -c"
    # Control: 300 000 bytes read at once
    out = machine.succeed(worker("r4a", f"queue run -- head -c 300000 /dev/zero | wc -c; {kept}"))
    assert out.split() == ["300000", "300000"], out
    # The reader takes a third, pauses for two seconds after the command has ended, and takes the rest
    out = machine.succeed(worker("r4b", f"queue run -- head -c 180000 /dev/zero | (head -c 60000 > /dev/null; sleep {2 * pace}; wc -c); {kept}"))
    print("R4:", out)
    assert out.split() == ["120000", "180000"], f"the reader got {out.split()[0]} of the remaining 120000 bytes, and the kept file holds {out.split()[-1]} of 180000"
    # The same on the error stream, and with a process left behind that still holds both streams
    out = machine.succeed(worker("r4c", f"queue run -- bash -c 'sleep 62 & head -c 180000 /dev/zero >&2' 2>&1 >/dev/null | (head -c 60000 > /dev/null; sleep {2 * pace}; wc -c); {kept}"))
    print("R4, the error stream, with a process left behind:", out)
    assert out.split() == ["120000", "180000"], out
    assert not running("sleep 62")

with subtest("N1: a job's environment is not in the list of processes"):
    # The value is read from a file inside the sandbox, so that no command line of this test holds it
    machine.succeed(f"echo planted-value-4711 > {folders}/alpha/b1/a/reports/token && chown {user} {folders}/alpha/b1/a/reports/token")
    # (the job waits at a gate while this test looks at the processes)
    background(worker("a", 'export SECRET_TOKEN=$(cat ../reports/token); queue run -- bash -c \'echo "inside=$SECRET_TOKEN"; ' + gate("n1-seen") + "'"), "/tmp/n1")
    machine.wait_until_succeeds("grep -q inside= /tmp/n1", timeout=30 * pace)
    listed = machine.succeed("ps -eo args | grep -c 'planted-value-471[1]' || true; cat /proc/[0-9]*/cmdline 2>/dev/null | tr '\\0' ' ' | grep -c 'planted-value-471[1]' || true").split()
    # Control: the job has the value in its environment, where only the user's own processes can read it
    holders = int(machine.succeed("(grep -lz 'planted-value-471[1]' /proc/[0-9]*/environ 2>/dev/null || true) | wc -l"))
    print("N1:", machine.succeed("cat /tmp/n1").strip(), "| in command lines:", listed, "| processes with it in their environment:", holders)
    assert listed == ["0", "0"] and holders >= 1 and "inside=planted-value-4711" in machine.succeed("cat /tmp/n1"), (listed, holders)
    openGate("n1-seen")
    sandboxEnded("a")

with subtest("G4: two parallel jobs do not run at once, a parallel and an ordinary job do"):
    mark = f'date +%s.%N > $WORKER_SCRATCH/start; sleep {3 * pace}; date +%s.%N > $WORKER_SCRATCH/end'
    def spans(jobs):
        machine.succeed("(" + " ".join(f"({worker(name, f'queue {mode} -- bash -c {shlex.quote(mark)}', project)}) > /dev/null 2>&1 &" for name, mode, project in jobs) + " wait)")
        return [[float(machine.succeed(f"cat {areas}/{project}/b1/{name}/{point}")) for point in ("start", "end")] for name, _, project in jobs]
    first, second = spans([("a", "run --parallel", "alpha"), ("b", "run --parallel", "beta")])
    print("G4 two parallel jobs:", first, second)
    assert first[1] <= second[0] or second[1] <= first[0], (first, second)
    first, second = spans([("a", "run --parallel", "alpha"), ("b", "run", "beta")])
    print("G4 parallel and ordinary:", first, second)
    assert first[0] < second[1] and second[0] < first[1], (first, second)

with subtest("V6: a job's sandbox is the agent's: the same mounts, the same answers"):
    probe = (
        "findmnt -rn -o TARGET,VFS-OPTIONS | grep -v '^/run/worker ' | sort;"
        " for p in . ../reports ../records $WORKER_SCRATCH ~ /tmp ~/.ssh /etc; do if touch $p/probe 2>/dev/null; then echo \"$p writable\"; rm -f $p/probe; else echo \"$p protected\"; fi; done;"
        " echo pid1=$(cat /proc/1/comm); if unshare --user true 2>/dev/null; then echo namespaces=allowed; else echo namespaces=refused; fi;"
        " if [ -e /run/user ] || [ -e /sys/fs/cgroup ] || [ -n \"${DBUS_SESSION_BUS_ADDRESS:-}\" ]; then echo session=visible; else echo session=hidden; fi"
    )
    machine.succeed("cat > /tmp/probe.sh <<'END'\n" + probe + "\nEND", f"install -o {user} -m 755 /tmp/probe.sh {folders}/alpha/b1/a/repo/probe.sh")
    agent = machine.succeed(worker("a", "bash probe.sh"))
    queued = machine.succeed(worker("a", "queue run -- bash probe.sh"))
    print("V6 agent:", agent)
    assert agent == queued, f"agent:\n{agent}\njob:\n{queued}"
    for expected in ["pid1=bwrap", "namespaces=refused", "session=hidden", ". writable", "../records protected", "/etc protected"]:
        assert expected in agent, agent
    # Only the agent has the broker's socket
    out = machine.succeed(worker("a", 'ls /run/worker; queue run -- bash -c "ls /run/worker 2>&1; echo \\"job=\\$?\\""'))
    assert "queue.sock" in out and "job=2" in out, out

with subtest("V4: a job reaches what its worker reaches and no more; a request changes nothing outside the job"):
    machine.succeed(asUser("cat ~/.ssh/id_test && touch ~/beta/control && rm ~/beta/control"), worker("a2", "echo of-a2 > ../reports/r; echo of-a2 > $WORKER_SCRATCH/d"))
    reach = f'cat ~/.ssh/id_test; echo "key=$?"; cat {folders}/alpha/b1/a2/reports/r; echo "folder=$?"; cat {areas}/alpha/b1/a2/d; echo "area=$?"; echo x > ~/beta/intruder; echo "project=$?"'
    out = machine.succeed(worker("a", f"queue run -- bash -c {shlex.quote(reach)}") + " 2>&1")
    print("V4 reach:", out)
    assert "key=1" in out and "folder=1" in out and "area=1" in out and "project=1" in out and "secret" not in out and "of-a2" not in out, out
    machine.fail(f"test -e {home}/beta/intruder")

    # Requests written by hand: the broker refuses whatever is not exactly a request
    raw = '''
import json, socket, struct, sys
request, count, length = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
body = request.encode()
connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
connection.connect("/run/worker/queue.sock")
socket.send_fds(connection, [struct.pack(">I", length if length else len(body)) + body], [0, 1, 2][:count])
print(connection.recv(65536).decode().strip())
'''
    machine.succeed("cat > /tmp/raw.py <<'END'\n" + raw + "\nEND", f"install -o {user} -m 644 /tmp/raw.py {folders}/alpha/b1/a/repo/raw.py")
    good = {"mode": "run", "command": ["echo", "accepted"], "folder": f"{folders}/alpha/b1/a/repo", "environment": {"PATH": "/run/current-system/sw/bin"}}
    cases = [
        ("control", good, 3, 0, '"exit": 0'),
        ("extra field", dict(good, extra="x"), 3, 0, "exactly the fields"),
        ("missing field", {key: value for key, value in good.items() if key != "environment"}, 3, 0, "exactly the fields"),
        ("unknown mode", dict(good, mode="root"), 3, 0, "unknown mode"),
        ("command as text", dict(good, command="echo accepted"), 3, 0, "list of strings"),
        ("relative folder", dict(good, folder="repo"), 3, 0, "absolute path"),
        ("environment as list", dict(good, environment=["A=b"]), 3, 0, "maps names to strings"),
        ("too large", good, 3, 2000000, "larger than"),
        ("one descriptor", good, 1, 0, "exactly three descriptors"),
    ]
    for label, request, count, length, expected in cases:
        out = machine.succeed(worker("a", f"python3 raw.py {shlex.quote(json.dumps(request))} {count} {length}") + " 2>&1")
        print(f"V4 {label}:", out.strip())
        assert expected in out and (("accepted" in out) == (label == "control")), f"{label}: {out}"
    # A folder outside the worker's view: refused inside the job's sandbox, nothing runs
    # (the project's own folder is no longer among them: an implementer now sees the history in it, read-only)
    for folder in [f"{home}/beta", f"{folders}/alpha/b1/a2", "/root"]:
        out = machine.succeed(worker("a", f"python3 raw.py {shlex.quote(json.dumps(dict(good, folder=folder)))} 3 0") + " 2>&1")
        assert "does not exist in this worker's view; nothing was run" in out and '"exit": 2' in out and "accepted" not in out, out

    # Finding 1 and A1: no part of a request becomes an option of the job's sandbox, and none is rewritten on the way
    machine.succeed(asUser("mkdir -p ~/outside && echo outside-content > ~/outside/marker"))
    nul = "\0"
    shown = ["cat", "/tmp/shown/marker"]
    hostile = [
        # Control: the same request with a plain value; the folder outside the view is not there to read
        ("control", dict(good, command=shown, folder="/", environment={"PATH": "/run/current-system/sw/bin", "A": "plain"}), "No such file or directory"),
        # R1 of the review: a value that ends its word and goes on with a mount option
        ("NUL in a value", dict(good, command=shown, folder="/", environment={"PATH": "/run/current-system/sw/bin", "A": f"x{nul}--ro-bind{nul}{home}/outside{nul}/tmp/shown"}), "holds a NUL character"),
        ("NUL in a name", dict(good, environment={f"A{nul}--ro-bind": "x"}), "is not a name of the environment"),
        ("NUL in a word of the command", dict(good, command=["echo", f"accepted{nul}more"]), "holds a NUL character"),
        ("NUL in the folder", dict(good, folder=f"/tmp{nul}/x"), "holds a NUL character"),
        # X3 of the deep review: names that are options of bwrap
        ("an option as a name", dict(good, command=["bash", "-c", "ls /--setenv"], environment={"A": "$NOPE_VARIABLE", "--bind": f"{home}/.ssh", "--unsetenv": "ZZ"}), "is not a name of the environment"),
        ("the whole machine as a name's value", dict(good, command=["bash", "-c", f"echo outside > /--setenv{home}/written-through-the-queue"], environment={"A": "$NOPE_VARIABLE", "--bind": "/"}), "is not a name of the environment"),
        ("a name that starts with a digit", dict(good, environment={"1A": "x"}), "is not a name of the environment"),
    ]
    for label, request, expected in hostile:
        out = machine.succeed(worker("a", f"python3 raw.py {shlex.quote(json.dumps(request))} 3 0") + " 2>&1")
        print(f"finding 1, {label}:", out.strip())
        assert expected in out and "outside-content" not in out and "accepted" not in out and "secret" not in out, f"{label}: {out}"
        assert ("refused" in out) == (label != "control"), f"{label}: {out}"
    machine.succeed(f"test ! -e {home}/written-through-the-queue && test ! -e {home}/.ssh/planted")
    # X3: a value that looks like a variable arrives as it is, and nothing is mounted for it
    request = dict(good, command=["bash", "-c", 'ls -d /--setenv 2>&1 | tail -n 1; echo "A=[$A]"'], environment={"PATH": "/run/current-system/sw/bin", "A": "$NOPE_VARIABLE", "ZZ": "y"})
    out = machine.succeed(worker("a", f"python3 raw.py {shlex.quote(json.dumps(request))} 3 0") + " 2>&1")
    print("X3, a value that looks like a variable:", out)
    assert "A=[$NOPE_VARIABLE]" in out and "No such file or directory" in out, out
    # X1 and X2: ${...} in the launcher's own arguments and in a queued command is not replaced by anything from outside the sandbox
    lines = {
        "x1.sh": 'echo "from a file: [${XDG_RUNTIME_DIR:-unset}]"',
        "x2.sh": 'queue run -- bash -c \'echo "job argument: [${XDG_RUNTIME_DIR}] [${MANAGERPID}] [${NOPE_VARIABLE}]"\'; queue run -- echo \'$XDG_RUNTIME_DIR\' \'$NOPE_VARIABLE\' \'${HOME}\' end',
        "ordinary.sh": (
            "export ODD=$'two  words \"double\" \\'single\\' `tick`\\nsecond line $HOME ${HOME} $(id)'\n"
            "queue run -- bash -c 'printf %s \"$ODD\"' > got; printf %s \"$ODD\" > want; cmp got want && echo arrived-unchanged\n"
            "f() { :; }; export -f f; queue run -- echo with-a-function 2> said; grep -c 'not passed to the job.*BASH_FUNC_f' said"
        ),
    }
    for name, text in lines.items():
        machine.succeed(f"printf '%s\n' {shlex.quote(text)} > /tmp/{name}", f"install -o {user} -m 755 /tmp/{name} {folders}/alpha/b1/a/repo/{name}")
    out = machine.succeed(worker("a", "bash x1.sh")) + machine.succeed(worker("a", 'echo "argument: [${XDG_RUNTIME_DIR}] [${NOPE_VARIABLE}] [$HOME]"'))
    print("X1:", out)
    assert out.splitlines() == ["from a file: [unset]", f"argument: [] [] [{home}]"], out
    out = machine.succeed(worker("a", "bash x2.sh"))
    print("X2:", out)
    assert out.splitlines() == ["job argument: [] [] []", "$XDG_RUNTIME_DIR $NOPE_VARIABLE ${HOME} end"], out
    # Control: an ordinary value with spaces, quotes, a newline and things that look like variables and commands arrives unchanged;
    # a shell's exported function, whose name is no plain name, stays behind and the client says so
    out = machine.succeed(worker("a", "bash ordinary.sh"))
    print("ordinary values:", out)
    assert out.splitlines() == ["arrived-unchanged", "with-a-function", "1"], out

    # An environment that names programs: they run inside the job, and nowhere else
    plant = (
        "m=$WORKER_SCRATCH/m; mkdir -p $m;"
        " printf 'echo bash-env >> %s/inside; echo bash-env >> $HOME/marker-outside\\n' $m > $m/benv.sh;"
        " printf 'import os\\nopen(\"%s/inside\", \"a\").write(\"python-path\\\\n\")\\nopen(os.path.expanduser(\"~/marker-outside\"), \"a\").write(\"python-path\\\\n\")\\n' $m > $m/sitecustomize.py;"
        " for tool in bwrap systemd-run systemctl; do printf '#!/bin/sh\\necho path-%s >> $HOME/marker-outside\\n' $tool > $m/$tool; chmod +x $m/$tool; done;"
        " BASH_ENV=$m/benv.sh PYTHONPATH=$m PATH=$m:$PATH LD_PRELOAD=/nonexistent/planted.so queue run -- bash -c 'python3 -c pass; command -v bwrap' 2>&1; cat $m/inside"
    )
    out = machine.succeed(worker("a", plant))
    print("V4 environment:", out)
    # Control: the planted settings did arrive in the job
    assert f"{areas}/alpha/b1/a/m/bwrap" in out and "python-path" in out and "bash-env" in out and "planted.so" in out, out
    machine.fail(f"test -e {home}/marker-outside")
    # Nothing outside the job loaded the planted library: such a process would say so in the journal, as the job did above
    # (the first version of this check searched for the library's name, which was there because systemd logged the job's command line)
    journal = machine.succeed("journalctl --no-pager | grep -c 'cannot be preloaded' || true").strip()
    assert journal == "0", journal
    # And the request's environment is not written into the user's journal
    assert machine.succeed("journalctl --no-pager _UID=1000 | grep -c 'planted.so' || true").strip() == "0"

with subtest("V7: queue inside a job runs directly; a sandbox's requests are limited"):
    out = machine.succeed(worker("a", "queue exclusive -- queue run -- echo nested-ran") + " 2>&1")
    print("V7 nested:", out)
    assert "nested-ran" in out and "running this command directly" in out, out
    # Eight requests wait or run; the ninth is refused
    # (the eight wait at a gate, which the ninth's refusal opens; the ninth is asked for when the broker counts eight)
    eight = f"for i in 1 2 3 4 5 6 7 8; do queue run -- bash -c {shlex.quote(gate('v7-ninth'))} & done"
    out = machine.succeed(worker("a", eight + '; until queue status | grep -q "8 of 8 requests"; do sleep 0.2; done; queue run -- echo ninth-ran; echo "ninth=$?"; queue status; touch $WORKER_SCRATCH/v7-ninth; wait') + " 2>&1")
    print("V7 limit:", out)
    assert "ninth=2" in out and "which is the limit" in out and "ninth-ran" not in out and "8 of 8 requests" in out, out

with subtest("G2: twenty short jobs at once from three sandboxes all start and end"):
    burst = lambda count: f'for i in $(seq {count}); do (queue run -- true && echo job-ok) & done; wait'
    machine.succeed("(" + worker("a", burst(7)) + " > /tmp/g2a 2>&1 & " + worker("a2", burst(7)) + " > /tmp/g2b 2>&1 & " + worker("b", burst(6), "beta") + " > /tmp/g2c 2>&1 & wait)")
    out = machine.succeed("cat /tmp/g2a /tmp/g2b /tmp/g2c")
    assert out.count("job-ok") == 20, out

with subtest("G3: fifty connections without a request do not stop the queue"):
    idle = '''
import socket, subprocess, sys, time
connections = []
for _ in range(50):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect("/run/worker/queue.sock")
    connections.append(connection)
print("status:", subprocess.run(["queue", "status"], capture_output=True, text=True).stdout.strip().splitlines()[-1])
# (the broker gives a connection ten seconds for its request)
time.sleep(10 + 2 * int(sys.argv[1]))
answers = []
for connection in connections:
    connection.settimeout(0.2)
    try:
        answers.append(connection.recv(4096).decode())
    except OSError:
        answers.append("")
print("closed to make room:", sum("too many connections" in answer for answer in answers))
print("timed out:", sum("no complete request arrived" in answer for answer in answers))
print("status afterwards:", subprocess.run(["queue", "status"], capture_output=True, text=True).stdout.strip().splitlines()[-1])
'''
    machine.succeed("cat > /tmp/idle.py <<'END'\n" + idle + "\nEND", f"install -o {user} -m 644 /tmp/idle.py {folders}/alpha/b1/a/repo/idle.py")
    background(worker("a", f"python3 idle.py {pace}; {gate('g3-seen')}"), "/tmp/g3")
    machine.wait_until_succeeds("grep -q 'status afterwards' /tmp/g3", timeout=60 * pace)
    peak = int(machine.succeed(f"cat {cgroup}/workers.slice/workers-brokers.slice/broker-worker:alpha:b1:a.service/memory.peak"))
    out = machine.succeed("cat /tmp/g3")
    print("G3:", out, "broker peak bytes:", peak)
    lines = dict(line.split(": ", 1) for line in out.strip().splitlines())
    assert lines["status"].startswith("this sandbox: 0 of 8") and lines["status afterwards"].startswith("this sandbox: 0 of 8"), out
    # Sixteen may wait at a time: the others were closed to make room, and the sixteen ran into the time limit
    assert int(lines["closed to make room"]) >= 34 and int(lines["closed to make room"]) + int(lines["timed out"]) == 50, out
    assert peak < 64 * 1024 * 1024, peak
    openGate("g3-seen")
    sandboxEnded("a")

with subtest("B2: the folder of the broker's socket takes no file, and the queue works all the same"):
    out = machine.succeed(worker("a", 'head -c 1M /dev/zero > /run/worker/fill; echo "write=$?"; queue run -- echo still-works; queue status | tail -n 1; echo "in the folder: $(ls /run/worker)"') + " 2>&1")
    print("B2:", out)
    assert "write=1" in out and "Read-only file system" in out and "still-works" in out and "this sandbox: 0 of 8" in out, out
    assert out.strip().splitlines()[-1] == "in the folder: queue.sock", out
    # C5 of the deep review: when the sandbox has ended, its folder of the runtime state is gone (it used to stay, and this
    # test looked into it here)
    machine.wait_until_succeeds("! test -e /run/user/1000/workers/worker:alpha:b1:a", timeout=10 * pace)

with subtest("B4: a job ends with its command, and what the command left behind ends with it"):
    timed = lambda command: f's=$(date +%s%N); timeout {25 * pace} queue run -- bash -c {shlex.quote(command)}; echo "exit=$? after $(( ($(date +%s%N) - s) / 1000000 )) ms"'
    machine.succeed(f"printf '%s\\n' {shlex.quote(timed('sleep 61 & echo started'))} {shlex.quote(timed('sleep 3; echo late'))} > /tmp/y1.sh", f"install -o {user} -m 755 /tmp/y1.sh {folders}/alpha/b1/a/repo/y1.sh")
    out = machine.succeed(worker("a", "bash y1.sh") + " 2>&1")
    print("B4 (Y1 of the deep review):", out)
    lines = out.strip().splitlines()
    # The job whose command left a process behind: ended with the command, with its status, within two seconds; on an emulated
    # machine, where starting and ending a job alone takes longer than that, within half of the 61 seconds of what was left behind
    assert lines[0] == "started" and lines[1].startswith("exit=0 after ") and int(lines[1].split()[2]) < (30000 if emulated else 2000), out
    # Control: a job is not cut short while its command runs
    assert lines[2] == "late" and lines[3].startswith("exit=0 after ") and int(lines[3].split()[2]) >= 3000, out
    entries = [json.loads(line) for line in machine.succeed(f"tail -n 4 {folders}/alpha/b1/a/records/runs.jsonl").splitlines()]
    assert machine.succeed(f"cat {entries[1]['output']}").strip() == "started" and entries[1]["exit"] == 0, entries
    assert not running("sleep 61")

with subtest("C2, C3 and the review's second small point: a request that cannot be read is answered, in time, and leaves nothing open"):
    hostile = r"""
import socket, struct, time

def send(body, announced=None):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect("/run/worker/queue.sock")
    message = struct.pack(">I", announced or len(body)) + body
    sent = socket.send_fds(connection, [message[:32768]], [0, 1, 2])
    return connection, message[sent:]

def answer(connection, rest):
    try:
        connection.sendall(rest)
        connection.settimeout(5)
        return connection.recv(65536).decode().strip()[:160] or "<closed without an answer>"
    except OSError as error:
        return f"<error: {error}>"

# E4 of the deep review: lists nested deeper than the reader goes
for index in range(5):
    print("nested:", answer(*send(b"[" * 200000)))
# Half of a surrogate pair, in a word of the command and in a value of the environment
for body in (b'{"mode": "run", "command": ["echo", "accepted-\\ud800"], "folder": "/", "environment": {}}', b'{"mode": "run", "command": ["echo", "accepted"], "folder": "/", "environment": {"A": "\\udfff"}}'):
    for index in range(3):
        print("surrogate:", answer(*send(body)))
# Control: the same request without the broken character runs
print("control:", answer(*send(b'{"mode": "run", "command": ["true"], "folder": "/", "environment": {}}')))
# E11 of the deep review: a request that arrives one byte at a time
connection, _ = send(b"{", 1000)
start, said = time.time(), ""
connection.settimeout(2)
while (time.time() - start < 40) and not said:
    try:
        said = connection.recv(4096).decode().strip() or "<closed without an answer>"
    except socket.timeout:
        try:
            connection.send(b" ")
        except OSError:
            said = "<closed without an answer>"
print(f"slow: after {time.time() - start:.0f} s: {said}")
print("hostile-done")
"""
    machine.succeed("cat > /tmp/hostile.py <<'END'\n" + hostile + "\nEND", f"install -o {user} -m 644 /tmp/hostile.py {folders}/alpha/b1/a/repo/hostile.py")
    # (the sandbox says when it runs, which it does once its broker listens, and waits at a gate until the broker's
    # descriptors are counted; at the end it waits until they are counted again)
    background(worker("a", f"echo sandbox-runs; {gate('c2-go')}; python3 hostile.py; {gate('c2-end')}"), "/tmp/hostile")
    machine.wait_until_succeeds("grep -q sandbox-runs /tmp/hostile", timeout=30 * pace)
    pid = machine.succeed(asUser("systemctl --user show -p MainPID --value broker-worker:alpha:b1:a.service")).strip()
    before = machine.succeed(f"ls /proc/{pid}/fd | wc -l").strip()
    openGate("c2-go")
    machine.wait_until_succeeds("grep -q hostile-done /tmp/hostile", timeout=90 * pace)
    # Every connection is closed again: at once on this machine's scale, so the count is awaited for a few seconds and then judged
    until(lambda: machine.succeed(f"ls /proc/{pid}/fd | wc -l").strip() == before, timeout=5, required=False)
    after = machine.succeed(f"ls /proc/{pid}/fd | wc -l").strip()
    out = machine.succeed("cat /tmp/hostile")
    print("C2, C3:", out, "the broker's descriptors before and after:", before, after)
    lines = out.strip().splitlines()
    assert [line for line in lines if line.startswith("nested:")] == ['nested: {"refused": "the request is not JSON"}'] * 5, out
    assert [line for line in lines if line.startswith("surrogate:")] == ['surrogate: {"refused": "a value of the environment, a word of the command or the folder is not valid Unicode"}'] * 6, out
    assert 'control: {"exit": 0}' in lines and "accepted" not in out, out
    slow = [line for line in lines if line.startswith("slow:")][0]
    assert "no complete request arrived within 10 seconds" in slow and 9 <= int(slow.split()[2]) <= (12 + 2 * pace if emulated else 12), out
    assert before == after, (before, after)
    assert machine.succeed("journalctl --no-pager _UID=1000 | grep -c -e RecursionError -e Traceback || true").strip() == "0"
    openGate("c2-end")
    sandboxEnded("a")

with subtest("G1: nothing of a sandbox outlives it, and nothing keeps what it was started with"):
    # Which programs hold one of the three files open, in one pass over every process's descriptors
    holders = r'''
find /proc/[0-9]*/fd -maxdepth 1 \( -lname /tmp/g1-in -o -lname /tmp/g1-fifo -o -lname /tmp/g1-err \) -printf '%h %l\n' 2>/dev/null | sort -u | while read -r folder target; do
  echo "$(cat ${folder%/fd}/comm 2>/dev/null) $target"
done | sort | uniq -c
'''
    machine.succeed("cat > /tmp/holders.sh <<'END'\n" + holders + "\nEND")
    machine.succeed("rm -f /tmp/g1-*; mkfifo /tmp/g1-fifo; echo input > /tmp/g1-in; touch /tmp/g1-err; chmod 666 /tmp/g1-*; (cat /tmp/g1-fifo > /tmp/g1-out 2>&1 &)")
    # Processes that try to stay: in the background, in a session of their own, and from inside a queued job
    # (the sandbox's own command waits at a gate while this test looks at what there is)
    stay = 'sleep 1000 & setsid sleep 1001 & queue run -- bash -c "setsid sleep 1002 & sleep 1003" & ' + gate("g1-leave") + "; echo leaving"
    ofSandbox = "worker:alpha:b1:a.scope broker-worker:alpha:b1:a.service 'job-worker:alpha:b1:a-*'"
    # Started through runuser, which hands the three files to the sandbox as they are; sudo would put pipes of its own in between
    environment = f"HOME={home} USER={user} XDG_RUNTIME_DIR=/run/user/1000 PATH=/run/wrappers/bin:/run/current-system/sw/bin"
    command = f"cd ~/alpha && worker-shell --branch b1 --name a -c {shlex.quote(stay)}"
    machine.succeed(f"(runuser -u {user} -- env -i {environment} bash -c {shlex.quote(command)} < /tmp/g1-in > /tmp/g1-fifo 2> /tmp/g1-err) > /dev/null 2>&1 &")
    machine.wait_until_succeeds("pgrep -x -f 'sleep 1002'", timeout=20 * pace)
    # Control: while it runs, all of this is there to be found
    units = userUnits(ofSandbox)
    during = machine.succeed("bash /tmp/holders.sh")
    print("G1 during:", during, units)
    for expected in ["sleep /tmp/g1-in", "sleep /tmp/g1-fifo", "sleep /tmp/g1-err", "bwrap /tmp/g1-fifo", "queue-job /tmp/g1-fifo"]:
        assert expected in during, during
    assert len(units) == 3 and running("sleep 1000") and running("sleep 1001") and running("sleep 1002") and running("sleep 1003")
    openGate("g1-leave")
    sandboxEnded("a")
    # Within three seconds of the sandbox's end, nothing of it is left
    until(lambda: machine.succeed("bash /tmp/holders.sh").strip() == "" and userUnits(ofSandbox) == [], timeout=3, required=False)
    after = machine.succeed("bash /tmp/holders.sh")
    print("G1 after:", after, userUnits(ofSandbox))
    # Nothing holds any of the three; the reader that this test put on the pipe has ended too, which it does when the last writer is gone
    assert after.strip() == "", after
    machine.fail("pgrep -x cat")
    assert userUnits(ofSandbox) == [] and not running("sleep 1000") and not running("sleep 1001") and not running("sleep 1002") and not running("sleep 1003")
    assert machine.succeed(f"find {cgroup}/workers.slice -name '*worker:alpha:b1:a*' | wc -l").strip() == "0"
    assert machine.succeed("cat /tmp/g1-out").strip() == "leaving"


with subtest("Modes: a timing job runs beside a run job; exclusive waits for both and holds the next back"):
    mark = f'date +%s.%N > $WORKER_SCRATCH/start; sleep {3 * pace}; date +%s.%N > $WORKER_SCRATCH/end'
    jobs = [("a", 0, "run", "alpha"), ("a2", 0, "timing", "alpha"), ("b", 1 * pace, "exclusive", "beta"), ("c", 2 * pace, "timing", "alpha")]
    machine.succeed("(" + " ".join(f"(sleep {delay}; {worker(name, f'queue {mode} -- bash -c {shlex.quote(mark)}', project)}) > /dev/null 2>&1 &" for name, delay, mode, project in jobs) + " wait)")
    spans = {name: [float(machine.succeed(f"cat {areas}/{project}/b1/{name}/{point}")) for point in ("start", "end")] for name, _, _, project in jobs}
    print("modes:", spans)
    # The run job and the first timing job overlap; the exclusive job starts after both ended; the second timing job after the exclusive one
    assert spans["a"][0] < spans["a2"][1] and spans["a2"][0] < spans["a"][1], spans
    assert max(spans["a"][1], spans["a2"][1]) <= spans["b"][0] and spans["b"][1] <= spans["c"][0], spans

with subtest("V3: an allocation above the agent's budget is stopped when run directly and succeeds through the queue"):
    for label, start in [("worker", lambda script: worker("a", script)), ("plain", plainSession)]:
        out = machine.succeed(start(f'{allocate % (300, 0)}; echo "direct=$?"; queue run -- {allocate % (300, 0)}; echo "queued=$?"') + " 2>&1")
        print(f"V3 {label}:", out)
        assert "direct=137" in out and "queued=0" in out and out.count("held") == 1, out
    # The record of the queued run says how much memory the job used at most: the 300 MiB, and not twice as much
    peak = record("a")["memory_peak"]
    print("V3, the job's highest memory in its record:", peak)
    assert (300 << 20) <= peak < (420 << 20), peak
    # Control: outside a sandbox the allocation succeeds
    machine.succeed(asUser(allocate % (300, 0)) + " | grep -q held")
    plain = json.loads(machine.succeed(f"tail -n 1 {home}/.local/state/workers-plain/gamma-*/records.jsonl"))
    print("V3 plain record:", plain)
    assert plain["exit"] == 0 and plain["role"] == "plain" and plain["output"].startswith(f"{areas}/gamma-"), plain

with subtest("V24: 2 GiB of output pass through a job without passing through the broker"):
    # (the session waits at a gate until the broker's memory is read)
    script = '( queue run -- bash -c "head -c 2147483648 /dev/zero; exit 7"; echo "status=$?" >&2 ) | wc -c; ' + gate("v24-seen")
    background(plainSession(script), "/tmp/v24")
    machine.wait_until_succeeds("grep -q status= /tmp/v24 && grep -q 2147483648 /tmp/v24", timeout=120 * pace)
    peak = int(machine.succeed(f"cat {cgroup}/workers.slice/workers-brokers.slice/broker-pi-gamma-*.service/memory.peak"))
    machine.succeed(f"for area in {areas}/gamma-*/plain/session; do touch $area/v24-seen; done")
    machine.wait_until_succeeds(asUser("! systemctl --user list-units --plain --no-legend 'pi-gamma-*.scope' | grep -q ."), timeout=30 * pace)
    # C5: the ordinary sessions of this test left no folder of runtime state behind, and nothing runs now that could have one:
    # what is there are the locks of the workers' names and the status's own notes
    left = lambda: machine.succeed("find /run/user/1000/workers -mindepth 1 -maxdepth 1 ! -name '*.lock' ! -name 'status-notes.json*' ! -name timing-reserved -printf '%f\\n'").split()
    until(lambda: left() == [], timeout=10, required=False)
    assert left() == [], left()
    out = machine.succeed("cat /tmp/v24")
    print("V24:", out, "broker peak bytes:", peak)
    assert "2147483648" in out and "status=7" in out, out
    assert peak < 64 * 1024 * 1024, peak
    machine.succeed(f"rm -rf {areas}/gamma-*/plain/session/runs")

with subtest("V5: the sandbox killed, the client killed, the broker killed"):
    # The sandbox
    background(worker("a", "queue run -- sleep 300"), "/tmp/v5a")
    machine.wait_until_succeeds("pgrep -x -f 'sleep 300'")
    print("V5 units:", userUnits("'job-*'"), userUnits("'broker-*'"), userUnits("'worker-*'"))
    assert slot() == "taken" and userUnits("'job-*'") == ["job-worker:alpha:b1:a-1.scope"] and "broker-worker:alpha:b1:a.service" in userUnits("'broker-*'")
    machine.succeed(asUser("systemctl --user kill -s KILL worker:alpha:b1:a.scope"))
    machine.wait_until_fails("pgrep -x -f 'sleep 300'", timeout=15 * pace)
    machine.wait_until_succeeds(asUser("! systemctl --user is-active --quiet broker-worker:alpha:b1:a.service"), timeout=15 * pace)
    assert slot() == "free" and userUnits("'job-*'") == [], userUnits("'job-*'")

    # The client
    # (the client is killed when its job has a slot, and the sandbox goes on until the broker has let the request go)
    killed = 'queue run -- sleep 301 & until queue status | grep -q "^slot1 *taken"; do sleep 0.2; done; kill -KILL $!; until queue status | grep -q "this sandbox: 0 of"; do sleep 0.2; done; echo "sandbox-alive"'
    out = machine.succeed(worker("a", killed))
    assert "sandbox-alive" in out and not running("sleep 301") and slot() == "free" and userUnits("'job-*'") == [], out
    assert record("a")["stopped"] is True, record("a")

    # The broker: its running job ends, and queue refuses instead of running anything
    background(worker("a", 'queue run -- sleep 302; echo "first=$?"; queue run -- echo should-not-run; echo "second=$?"'), "/tmp/v5c")
    machine.wait_until_succeeds("pgrep -x -f 'sleep 302'")
    machine.succeed(asUser("systemctl --user kill -s KILL broker-worker:alpha:b1:a.service"))
    machine.wait_until_succeeds("grep -q second= /tmp/v5c", timeout=20 * pace)
    out = machine.succeed("cat /tmp/v5c")
    print("V5 broker killed:", out)
    assert "first=2" in out and "second=2" in out and "nothing was run" in out and "should-not-run" not in out, out
    machine.wait_until_fails("pgrep -x -f 'sleep 302'", timeout=15 * pace)
    assert slot() == "free" and userUnits("'job-*'") == [], userUnits("'job-*'")

with subtest("A name that runs is taken"):
    # (the first one says when its sandbox runs, and waits at a gate)
    background(worker("a", f"echo sandbox-runs; {gate('name-go')}"), "/tmp/name1")
    machine.wait_until_succeeds("grep -q sandbox-runs /tmp/name1", timeout=30 * pace)
    out = machine.fail(worker("a", "true") + " 2>&1")
    assert "already running" in out, out
    openGate("name-go")
    sandboxEnded("a")
    machine.succeed(worker("a", "true"))

with subtest("V2a: all agents together stay within their share of the processors"):
    two = "bash -c 'while :; do :; done' & bash -c 'while :; do :; done' & " + gate("v2a-measured")
    background(worker("a", two), "/dev/null")
    background(worker("a2", two), "/dev/null")
    machine.wait_until_succeeds("[ $(pgrep -c -x -f 'bash -c while :; do :; done') -ge 4 ]", timeout=60 * pace)
    usage = [int(machine.succeed(f"sleep {pause}; grep usage_usec {cgroup}/workers.slice/workers-agents.slice/cpu.stat | cut -d' ' -f2")) for pause in (0, 8)]
    cores = (usage[1] - usage[0]) / 8e6
    print("V2a cores used by four loops in two agents:", cores)
    # The limit is 1.5; control: the loops want four and get clearly more than one
    assert 1.2 < cores < 1.65, cores
    openGate("v2a-measured")
    openGate("v2a-measured", "a2")
    sandboxEnded("a")
    sandboxEnded("a2")

with subtest("V2b: the timing cores are cleared while a timing job runs, and only then"):
    background(worker("a", loop("loop-direct")), "/dev/null")
    background(worker("b", "queue run -- " + loop("loop-queued"), "beta"), "/dev/null")
    machine.succeed(asUser("systemd-run --user --quiet --unit=loop-desktop --slice=app.slice " + loop("loop-desktop")), asUser("systemd-run --user --quiet --unit=loop-late --slice=late.slice " + loop("loop-late")))
    tags = ["loop-direct", "loop-queued", "loop-desktop", "loop-late"]
    machine.wait_until_succeeds("pgrep -x -f 'bash -c while :; do :; done loop-queued'")
    before = {tag: allowed(tag)[0] for tag in tags}
    print("V2b before:", before)
    assert set(before.values()) == {"0-3"}, before
    # A build that a worker starts runs in the Nix daemon: never on the timing core
    build = (
        "NIX_REMOTE=daemon nix-build --no-out-link -E 'derivation { name = \"cpus\"; system = builtins.currentSystem; builder = \"/bin/sh\";"
        " args = [ \"-c\" \"while read line; do case \\\"$line\\\" in Cpus_allowed_list*) echo \\\"$line\\\" > $out;; esac; done < /proc/self/status\" ]; }' > built 2> build-log; cat build-log; cat $(cat built)"
    )
    out = machine.succeed(worker("a2", build) + " 2>&1")
    print("V2b build:", out)
    assert out.split()[-2:] == ["Cpus_allowed_list:", "1-3"], out

    # (the timing job waits at a gate while this test looks at the loops)
    background(worker("c", f"queue timing -- bash -c {shlex.quote('grep Cpus_allowed_list /proc/self/status; ' + gate('v2b-seen'))}"), "/tmp/v2-timing")
    machine.wait_until_succeeds("grep -q Cpus_allowed_list /tmp/v2-timing", timeout=20 * pace)
    # The cores are cleared before the timing job starts; a loop that was on one of them is moved at its next turn
    until(lambda: "0" not in [allowed(tag)[1] for tag in tags], timeout=5, required=False)
    during = {tag: allowed(tag) for tag in tags}
    samples = [allowed(tag)[1] for tag in tags for _ in range(3)]
    print("V2b during:", during, samples, machine.succeed("cat /tmp/v2-timing"))
    assert {value[0] for value in during.values()} == {"1-3"} and "0" not in samples, (during, samples)
    assert machine.succeed("cat /tmp/v2-timing").split() == ["Cpus_allowed_list:", "0"]
    openGate("v2b-seen", "c")
    sandboxEnded("c")
    after = {tag: allowed(tag)[0] for tag in tags}
    print("V2b after:", after)
    assert set(after.values()) == {"0-3"}, after

    # The broker of a timing job is killed: the cores stay reserved, the status says so, and the next timing job gives them back
    machine.fail("journalctl --no-pager _SYSTEMD_USER_UNIT=workers-memory-watch.service | grep -q 'timing cores stay reserved'")
    background(worker("c", "queue timing -- sleep 310"), "/dev/null")
    machine.wait_until_succeeds("pgrep -x -f 'sleep 310'")
    machine.succeed(asUser("systemctl --user kill -s KILL broker-worker:alpha:b1:c.service"))
    machine.wait_until_fails("pgrep -x -f 'sleep 310'", timeout=15 * pace)
    reserved = {tag: allowed(tag)[0] for tag in tags}
    status = machine.succeed(worker("a2", "queue status"))
    print("V2b reserved:", reserved, status)
    assert set(reserved.values()) == {"1-3"} and "timing cores: reserved" in status and "timing       free" in status, (reserved, status)
    # N2: the watcher tells the user (control: it had nothing to tell before)
    machine.wait_until_succeeds("journalctl --no-pager _SYSTEMD_USER_UNIT=workers-memory-watch.service | grep -q 'timing cores stay reserved'", timeout=30 * pace)
    machine.succeed(worker("a2", "queue timing -- true"))
    restored = {tag: allowed(tag)[0] for tag in tags}
    assert set(restored.values()) == {"0-3"} and "timing cores: shared" in machine.succeed(worker("a2", "queue status")), restored
    machine.succeed("pkill -x -f 'bash -c while :; do :; done loop-[a-z]+'")
    sandboxEnded("a")
    sandboxEnded("b", "beta")

with subtest("V18: over the total, a job is stopped and not an agent; over the agents' total, an agent's process is stopped and not a job"):
    hold = lambda megabytes: allocate % (megabytes, 6 * pace)
    # Two jobs of 400 MiB against 640 MiB for everything (the second one as a timing job, since there is one slot)
    machine.succeed("(" + worker("a", f'queue run -- {hold(400)}; echo "job=$?"') + " > /tmp/v18a 2>&1 & " + worker("b", f'queue timing -- {hold(400)}; echo "job=$?"', "beta") + " > /tmp/v18b 2>&1 & wait)")
    out = machine.succeed("cat /tmp/v18a /tmp/v18b")
    print("V18 two jobs:", out)
    assert out.count("job=137") == 1 and out.count("job=0") == 1 and out.count("held") == 1, out
    # An agent holding 200 MiB and its own job of 500 MiB: the job goes
    out = machine.succeed(worker("a", f'{hold(200)} & sleep {pace}; queue run -- {hold(500)}; echo "job=$?"; wait; echo "agent=$?"') + " 2>&1")
    print("V18 job before agent:", out)
    assert "job=137" in out and "agent=0" in out and out.count("held") == 1, out
    # Two agents of 220 MiB each against 384 MiB for all agents, while a job runs
    machine.succeed(
        "(" + worker("a", f'{hold(220)}; echo "agent=$?"') + " > /tmp/v18c 2>&1 & " + worker("a2", f'{hold(220)}; echo "agent=$?"') + " > /tmp/v18d 2>&1 & "
        + worker("b", f'queue run -- bash -c "sleep {7 * pace}; echo job-done"', "beta") + " > /tmp/v18e 2>&1 & wait)"
    )
    out = machine.succeed("cat /tmp/v18c /tmp/v18d /tmp/v18e")
    print("V18 agents' total:", out)
    assert out.count("agent=137") == 1 and out.count("agent=0") == 1 and "job-done" in out, out
    machine.succeed(asUser("systemctl --user is-active desktop-standin.service"))
    watch = machine.succeed("journalctl --no-pager _SYSTEMD_USER_UNIT=workers-memory-watch.service | grep 'stopped for memory' | tail -n 3")
    print("V18 watcher:", watch)
    assert "stopped for memory" in watch, watch
    # The watcher also wrote every stop down, and `workers status` counts them. Whose job it was is in the job's own record;
    # whose agent, only if its resource group still existed when the watcher looked, two seconds later at most
    written = lambda: [json.loads(line) for line in machine.succeed(f"cat {home}/.local/state/workers/memory-stops.jsonl 2>/dev/null; true").splitlines()]
    until(lambda: sum(stop["count"] for stop in written()) >= 3, timeout=10)
    stops = written()
    document = json.loads(machine.succeed(asUser("workers status --json")))
    counted = document["machine"]["memoryStops"]
    print("V18, the stops as written down:", stops, "| in the status:", counted)
    # This subtest alone stopped three processes
    assert sum(stop["count"] for stop in stops) >= 3 and counted["count"] == sum(stop["count"] for stop in stops), (stops, counted)
    # The two jobs that were stopped: one of the two that ran together, and the one of worker a beside its own agent
    jobs = [stop for stop in counted["last"] if stop["what"] == "job"]
    assert len(jobs) >= 2 and {"alpha/b1/a"} <= {stop["worker"] for stop in jobs} <= {"alpha/b1/a", "beta/b1/b"}, counted
    assert [entry for entry in document["workers"] if (entry["project"], entry["name"]) == ("alpha", "a")][0]["memoryStops"]["count"] >= 1
    assert record("a")["memory_stops"] == 1 and record("a")["exit"] == 137, record("a")

with subtest("V22: a killed job and a reboot leave no slot taken"):
    background(worker("a", 'queue run -- sleep 303; echo "exit=$?"'), "/tmp/v22a")
    machine.wait_until_succeeds("pgrep -x -f 'sleep 303'")
    assert slot() == "taken"
    machine.succeed("pkill -KILL -x -f 'sleep 303'")
    machine.wait_until_succeeds("grep -q exit=137 /tmp/v22a", timeout=15 * pace)
    assert slot() == "free" and record("a")["exit"] == 137, record("a")
    # Two jobs run and one waits when the machine goes down
    background(worker("a", "queue run -- sleep 304"), "/dev/null")
    background(worker("a2", "queue run -- sleep 306"), "/dev/null")
    machine.wait_until_succeeds("pgrep -x -f 'sleep 304' && pgrep -x -f 'sleep 306'")
    background(worker("b", "queue run -- sleep 305", "beta"), "/dev/null")
    until(lambda: waiting() == 1, timeout=30)
    assert slot("slot1") == "taken" and slot("slot2") == "taken" and not running("sleep 305")
    machine.shutdown()
    machine.start()
    boot()
    assert slot("slot1") == "free" and slot("slot2") == "free" and slot("timing") == "free"
    out = machine.succeed(worker("b", "queue run -- echo ran-after-reboot; queue status", "beta"))
    print("V22:", out)
    assert "ran-after-reboot" in out and "timing cores: shared" in out, out
