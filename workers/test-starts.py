import json
import shlex

home = f"/home/{user}"
state = f"{home}/.local/state/workers"
folders = f"{home}/workers"
areas = f"{home}/scratch/workers"


def asUser(command):
    """Run one command as the user outside every sandbox"""
    _environment_ = f"HOME={home} USER={user} XDG_RUNTIME_DIR=/run/user/1000 PATH=/etc/profiles/per-user/{user}/bin:/run/wrappers/bin:/run/current-system/sw/bin"
    return f"sudo -u {user} env -i {_environment_} bash -c {shlex.quote(command)} < /dev/null"


def register(arguments, project=None):
    """Register one worker without starting its sandbox"""
    _project_ = project or f"{home}/projects with space/alpha"
    return asUser(f"cd {shlex.quote(_project_)} && pi --register-start {arguments}")


def shortStart(worker):
    """Start one worker only from its trusted identifier"""
    return asUser(f"workers start {shlex.quote(worker)}")


def continueStart(worker):
    """Continue one worker only from its trusted identifier"""
    return asUser(f"workers start --continue {shlex.quote(worker)}")


def command(worker):
    """Print one remembered command"""
    return asUser(f"workers command {shlex.quote(worker)}")


## Step 1. Prepare projects and shares
machine.start()
machine.wait_for_unit("multi-user.target")
machine.wait_for_unit("user@1000.service")
machine.succeed(
    asUser(
        f"mkdir -p {shlex.quote(home + '/projects with space/alpha')} {shlex.quote(home + '/projects with space/plain')} "
        f"{shlex.quote(home + '/repos/guarded/protected')} {shlex.quote(home + '/shared data/read only')} "
        f"{shlex.quote(home + '/shared data/write space')} {shlex.quote(home + '/movable old')}"
        f" && git init -q -b main {shlex.quote(home + '/projects with space/alpha')}"
        f" && echo base > {shlex.quote(home + '/projects with space/alpha/file')}"
        f" && git -C {shlex.quote(home + '/projects with space/alpha')} add ."
        f" && git -C {shlex.quote(home + '/projects with space/alpha')} -c user.name=t -c user.email=t@t commit -q -m base"
        f" && git -C {shlex.quote(home + '/projects with space/alpha')} branch b1"
        f" && git init -q -b main {shlex.quote(home + '/repos/guarded')}"
        f" && echo base > {shlex.quote(home + '/repos/guarded/file')}"
        f" && git -C {shlex.quote(home + '/repos/guarded')} add ."
        f" && git -C {shlex.quote(home + '/repos/guarded')} -c user.name=t -c user.email=t@t commit -q -m base"
        f" && git -C {shlex.quote(home + '/repos/guarded')} branch b1"
    )
)


## Step 2. A legacy registration exists before its first short start
with subtest("the first short start has a trusted specification before execution"):
    _output_ = machine.succeed(register("--branch b1 --name i1"))
    assert "workers start alpha/b1/i1" in _output_, _output_
    assert not machine.succeed(asUser(f"find {areas}/alpha/b1/i1 -type f 2> /dev/null || true")).strip()
    machine.succeed(shortStart("alpha/b1/i1"))
    _launcher_ = machine.succeed(f"cat {areas}/alpha/b1/i1/pi-launcher").strip()
    assert _launcher_ == "user-profile", _launcher_
    _before_ = machine.succeed("cat /tmp/start-before-alpha-b1-i1")
    assert "--role implementer" in _before_ and "--name i1" in _before_, _before_


## Step 3. Register nine workers, including a reviewer and paths with spaces
with subtest("nine specifications and reviewer target survive reboot"):
    for _number_ in range(2, 9):
        machine.succeed(register(f"--branch b1 --name i{_number_}"))
    machine.succeed(register("--role reviewer --branch b1 --name i1-r1 --of i1"))
    _workers_ = [f"alpha/b1/i{_number_}" for _number_ in range(1, 9)] + ["alpha/b1/i1-r1"]
    for _worker_ in _workers_:
        _remembered_ = machine.succeed(command(_worker_))
        assert f"workers start {_worker_}" not in _remembered_
        assert "pi " in _remembered_, _remembered_
    _reviewer_ = machine.succeed(command("alpha/b1/i1-r1"))
    assert "--role reviewer" in _reviewer_ and "--of i1" in _reviewer_, _reviewer_

    machine.shutdown()
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("user@1000.service")
    for _worker_ in _workers_:
        machine.succeed(command(_worker_))
    machine.succeed(shortStart("alpha/b1/i2"))
    assert machine.succeed("cat /tmp/start-before-alpha-b1-i2").strip()
    _freshArguments_ = machine.succeed(f"cat {areas}/alpha/b1/i2/pi-arguments").splitlines()
    assert _freshArguments_ == [], _freshArguments_
    machine.succeed(continueStart("alpha/b1/i3"))
    _continuedArguments_ = machine.succeed(f"cat {areas}/alpha/b1/i3/pi-arguments").splitlines()
    assert _continuedArguments_ == ["-c"], _continuedArguments_

with subtest("read-only and writable shares round-trip exactly"):
    machine.succeed(
        register(
            f"--branch b1 --name shares --allow-ro {shlex.quote(home + '/shared data/read only')} --allow {shlex.quote(home + '/shared data/write space')}"
        )
    )
    machine.succeed(shortStart("alpha/b1/shares"))
    _arguments_ = machine.succeed(f"cat {areas}/alpha/b1/shares/pi-arguments").splitlines()
    assert _arguments_ == [], _arguments_
    _modes_ = machine.succeed(f"cat {areas}/alpha/b1/shares/share-modes").splitlines()
    assert _modes_ == ["read-only", "writable"], _modes_
    assert machine.succeed(asUser(f"cat {shlex.quote(home + '/shared data/write space/from-worker')}")).strip() == "written"


## Step 4. Unsafe and one-use arguments never enter a remembered command or record
with subtest("secrets prompts unlock and selectors are not persisted"):
    machine.succeed(
        asUser(
            f"cd {shlex.quote(home + '/repos/guarded')}"
            " && pi --branch b1 --name unsafe --unlock --model 'model one' --offline"
            " --api-key 'api secret' --system-prompt 'prompt secret' --session 'session secret' 'initial secret'"
        )
    )
    _remembered_ = machine.succeed(command("guarded/b1/unsafe"))
    assert "--model 'model one'" in _remembered_ and "--offline" in _remembered_, _remembered_
    for _forbidden_ in ["api secret", "prompt secret", "session secret", "initial secret", "--unlock", "--api-key", "--system-prompt", "--session"]:
        assert _forbidden_ not in _remembered_, (_forbidden_, _remembered_)
    _records_ = machine.succeed(asUser(f"grep -R . {state}/guarded/start-specs || true"))
    for _forbidden_ in ["api secret", "prompt secret", "session secret", "initial secret", "--unlock"]:
        assert _forbidden_ not in _records_, (_forbidden_, _records_)

    _snapshot_ = machine.fail(register("--branch b1 --name snapshot --snapshots") + " 2>&1")
    assert "cannot be remembered" in _snapshot_, _snapshot_
    machine.fail(command("alpha/b1/snapshot") + " 2>&1")


## Step 5. A stale registered path refuses before Pi starts
with subtest("missing or moved shares refuse with their path"):
    machine.succeed(register(f"--branch b1 --name moved --allow-ro {shlex.quote(home + '/movable old')}"))
    machine.succeed(asUser(f"mv {shlex.quote(home + '/movable old')} {shlex.quote(home + '/movable new')}"))
    _refusal_ = machine.fail(shortStart("alpha/b1/moved") + " 2>&1")
    assert f"{home}/movable old" in _refusal_, _refusal_
    assert not machine.succeed(asUser(f"find {areas}/alpha/b1/moved -type f 2> /dev/null || true")).strip()


## Step 6. Status uses remembered starts and ordinary Pi remains ordinary
with subtest("status exposes the remembered short command"):
    _document_ = json.loads(machine.succeed(asUser("workers status --json")))
    _i1_ = next(_worker_ for _worker_ in _document_["workers"] if (_worker_.get("name") == "i1"))
    _strings_ = []

    def strings(value):
        if isinstance(value, str):
            _strings_.append(value)
        elif isinstance(value, dict):
            for _nested_ in value.values():
                strings(_nested_)
        elif isinstance(value, list):
            for _nested_ in value:
                strings(_nested_)

    strings(_i1_)
    assert "workers start alpha/b1/i1" in _strings_, _i1_

with subtest("plain pi creates no worker specification or command"):
    machine.succeed(asUser(f"cd {shlex.quote(home + '/projects with space/plain')} && pi"))
    _plainSpecs_ = machine.succeed(asUser(f"find {state} -path '*/start-specs/*' -type f -printf '%P\n' || true"))
    assert "plain" not in _plainSpecs_, _plainSpecs_
    machine.fail(command("plain/b1/plain") + " 2>&1")
