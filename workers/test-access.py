import json
import shlex
from typing import Annotated


def runAccessTest(
    machine: Annotated[object, "The NixOS test machine"],
    user: Annotated[str, "The test account"],
):
    """Exercise installed remembered starts, manager reads and bundles together"""
    _home_ = f"/home/{user}"
    _state_ = f"{_home_}/.local/state/workers"
    _folders_ = f"{_home_}/workers"
    _areas_ = f"{_home_}/scratch/workers"

    def asUser(command):
        """Run one command as the user outside every sandbox"""
        _environment_ = f"HOME={_home_} USER={user} XDG_RUNTIME_DIR=/run/user/1000 PATH=/etc/profiles/per-user/{user}/bin:/run/wrappers/bin:/run/current-system/sw/bin"
        return f"sudo -u {user} env -i {_environment_} bash -c {shlex.quote(command)} < /dev/null"

    def register(arguments, project="alpha"):
        """Register one installed worker start without running its sandbox"""
        return asUser(f"cd ~/{project} && pi --register-start {arguments}")

    def shortStart(worker):
        """Start one worker through its installed remembered command"""
        return asUser(f"workers start {shlex.quote(worker)}")

    def approve(worker):
        """Give one test implementer write authority without an intent form"""
        return asUser(f"printf '\\nyes\\n' | workers approve --without-form {shlex.quote(worker)}")

    ## Step 1. Prepare projects, trusted starts and a knowledge file that plain Pi must not receive
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("user@1000.service")
    machine.succeed(
        asUser(
            "mkdir -p ~/.config/git ~/alpha ~/plain"
            " && printf '[user]\\n\\tname = The User\\n\\temail = user@example.org\\n' > ~/.config/git/config"
            " && git init -q -b main ~/alpha"
            " && echo base > ~/alpha/base"
            " && git -C ~/alpha add ."
            " && git -C ~/alpha commit -q -m base"
            " && git -C ~/alpha branch b1"
        )
    )
    for _arguments_ in ["--branch b1 --name early", "--role manager", "--branch b1 --name late"]:
        machine.succeed(register(_arguments_))
    machine.succeed(approve("alpha/b1/early"))

    ## Step 2. Restart the user service and prove the remembered starts still run
    machine.succeed("systemctl restart user@1000.service")
    machine.wait_for_unit("user@1000.service")
    machine.succeed(shortStart("alpha/b1/early"))
    assert machine.succeed(f"cat {_folders_}/alpha/b1/early/reports/report").strip() == "early-report"
    machine.succeed(
        f"mkdir -p {_folders_}/alpha/knowledge/common",
        f"printf private-knowledge > {_folders_}/alpha/knowledge/common/material",
    )

    ## Step 3. Start the manager after the earlier worker, then create a later worker while that manager stays live
    machine.succeed(f"({shortStart('alpha/manager/manager')}) > /tmp/access-manager 2>&1 &")
    machine.wait_until_succeeds(
        f"test -e {_areas_}/alpha/manager/manager/manager-ready -o -e {_areas_}/alpha/manager/manager/worker-mount-present",
        timeout=60,
    )
    machine.succeed(f"test -e {_areas_}/alpha/manager/manager/manager-ready || {{ cat /tmp/access-manager; exit 1; }}")
    machine.succeed(approve("alpha/b1/late"), shortStart("alpha/b1/late"), f"touch {_areas_}/alpha/manager/manager/later-ready")
    machine.wait_until_succeeds(f"test -e {_areas_}/alpha/manager/manager/manager-done", timeout=60)
    machine.wait_until_succeeds(asUser("! systemctl --user is-active --quiet worker:alpha:manager:manager.scope"), timeout=60)

    _status_ = json.loads(machine.succeed(asUser("workers status --json")))
    _commands_ = {
        (_worker_["branch"], _worker_["name"]): _worker_.get("command", {}).get("value")
        for _worker_ in _status_["workers"]
        if (_worker_.get("project") == "alpha")
    }
    assert _commands_[("manager", "manager")] == "workers start alpha/manager/manager", _commands_
    assert _commands_[("b1", "early")] == "workers start alpha/b1/early", _commands_

    _output_ = machine.succeed("cat /tmp/access-manager")
    print("combined access manager:", _output_)
    for _expected_ in [
        "early-report",
        "early-draft",
        '"name": "early"',
        "late-report",
        "late-draft",
        '"name": "late"',
    ]:
        assert _expected_ in _output_, (_expected_, _output_)
    _managerRepo_ = f"{_folders_}/alpha/manager/manager/repo"
    assert machine.succeed(asUser(f"git -C {_managerRepo_} branch --show-current")).strip() == "b1"
    assert machine.succeed(f"cat {_managerRepo_}/early.txt {_managerRepo_}/late.txt").split() == ["early-committed", "late-committed"]
    for _worker_ in ["early", "late"]:
        machine.fail(asUser(f"git -C {_managerRepo_} show refs/workers/b1/{_worker_}:draft"))
        machine.succeed(f"test ! -e {_folders_}/alpha/b1/{_worker_}/reports/reader-write")

    ## Step 4. Plain Pi remains outside remembered starts, knowledge and worker broker commands
    machine.succeed(asUser("cd ~/plain && pi"))
    _plainResult_ = machine.succeed(f"find {_areas_} -path '*/plain/session/plain-result' -type f -print -quit").strip()
    assert _plainResult_, _plainResult_
    _plain_ = machine.succeed(f"cat {_plainResult_}")
    print("plain pi:", _plain_)
    assert _plain_.split() == ["role=unset", "reader=refused", "bundle=refused", "knowledge=absent"], _plain_
    assert not machine.succeed(asUser(f"find {_state_}/plain -path '*/start-specs/*' -type f -print 2> /dev/null || true")).strip()
