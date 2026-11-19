import re
import shlex
from typing import Annotated, Callable


def runBundleTest(
    machine: Annotated[object, "The NixOS test machine"],
    user: Annotated[str, "The test account"],
    home: Annotated[str, "The test account's home"],
    folders: Annotated[str, "The worker folders root"],
    areas: Annotated[str, "The worker scratch root"],
    asUser: Annotated[Callable[[str], str], "Wrap one host command as the test user"],
    start: Annotated[Callable[..., str], "Build one worker start command"],
    task: Annotated[Callable[..., str], "Build one manager task-file command"],
    gate: Annotated[Callable[[str], str], "Build one worker-side wait gate"],
    openGate: Annotated[Callable[[str, str], None], "Open one worker gate"],
    sandboxEnded: Annotated[Callable[..., None], "Wait for one worker sandbox to end"],
):
    """Exercise the late-worker bundle through one manager broker"""
    _commit_ = "git -c user.name=t -c user.email=t@t commit -q"

    ## Step 1. Start the manager before the target, then fetch and merge in that session
    _manager_ = task("late-bundle", "implementer", branch="b2") + ";" + task("link-bundle", "implementer", branch="b2")
    _manager_ += ";" + task("absent-tip", "implementer", branch="b2") + ";" + task("advanced-base", "implementer", branch="b2")
    _manager_ += ";" + task("no-common", "implementer", branch="b2") + ";" + task("bundle-reviewer", "reviewer", branch="b2")
    _manager_ += ";touch $WORKER_SCRATCH/ready;" + gate("bundle-go")
    _manager_ += (
        ";worker-bundle b2/late-bundle > $WORKER_SCRATCH/late.bundle;"
        "echo size=$(stat -c %s $WORKER_SCRATCH/late.bundle);"
        "git bundle list-heads $WORKER_SCRATCH/late.bundle;"
        "git fetch $WORKER_SCRATCH/late.bundle worker/b2/late-bundle:refs/workers/b2/late-bundle;"
        "git checkout -q b2;git merge -q --no-edit refs/workers/b2/late-bundle;"
        "cat late-file;git show refs/workers/b2/late-bundle:uncommitted 2>/dev/null || echo no-uncommitted;"
        "touch $WORKER_SCRATCH/done;" + gate("bundle-stop")
    )
    machine.succeed(f"({start('--role manager --name bundle-manager', _manager_)}) > /tmp/bundle-manager 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/bundle-manager/ready")

    ## Step 2. Commit one small change and leave another branch, uncommitted data and hostile config behind
    _late_ = (
        "echo committed > late-file;printf '*.fixture filter=hostile\\n' > .gitattributes;echo filtered > tracked.fixture;"
        f"git add late-file .gitattributes tracked.fixture;{_commit_} -m late;git branch unrelated;git checkout -q unrelated;"
        f"echo unrelated > unrelated-file;git add unrelated-file;{_commit_} -m unrelated;git checkout -q worker/b2/late-bundle;"
        "echo draft > uncommitted;mkdir hooks;"
        "printf '#!/bin/sh\ntouch /tmp/bundle-hook-ran\n' > hooks/pre-commit;"
        "printf '#!/bin/sh\ntouch /tmp/bundle-filter-ran\ncat\n' > hooks/filter;chmod +x hooks/*;"
        "git config core.hooksPath $PWD/hooks;git config filter.hostile.clean $PWD/hooks/filter;git config filter.hostile.smudge $PWD/hooks/filter"
    )
    machine.succeed(start("--branch b2 --name late-bundle", _late_))
    _workerRepo_ = f"{folders}/alpha/b2/late-bundle/repo"
    _head_ = machine.succeed(asUser(f"git -C {_workerRepo_} rev-parse worker/b2/late-bundle")).strip()
    _unrelated_ = machine.succeed(asUser(f"git -C {_workerRepo_} rev-parse unrelated")).strip()
    openGate("alpha/manager/bundle-manager", "bundle-go")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/bundle-manager/done")
    _out_ = machine.succeed("cat /tmp/bundle-manager")
    _size_ = int(re.search(r"size=(\d+)", _out_).group(1))
    assert (_size_ < 65536), _size_
    assert (_out_.count(f"{_head_} refs/heads/worker/b2/late-bundle") == 1), _out_
    assert ("committed" in _out_) and ("no-uncommitted" in _out_), _out_
    _managerRepo_ = f"{folders}/alpha/manager/bundle-manager/repo"
    machine.fail(asUser(f"git -C {_managerRepo_} cat-file -e {_unrelated_}"))
    assert (machine.succeed("test ! -e /tmp/bundle-hook-ran -a ! -e /tmp/bundle-filter-ran;echo safe").strip() == "safe")

    ## Step 3. Refuse implementer and reviewer identities, another project and another ref
    _socket_ = "/run/user/1000/workers/worker:alpha:manager:bundle-manager/socket/queue.sock"
    _ask_ = lambda _worker_, _path_: asUser(f"WORKER_QUEUE_SOCKET={_socket_} worker-bundle {_worker_} > {_path_}")
    _refused_ = machine.fail(start("--branch b2 --name late-bundle", "worker-bundle b2/late-bundle > /dev/null") + " 2>&1")
    assert ("only a manager" in _refused_), _refused_
    _reviewer_ = machine.fail(
        start("--role reviewer --branch b2 --name bundle-reviewer --of late-bundle", "worker-bundle b2/late-bundle > /dev/null") + " 2>&1"
    )
    assert ("only a manager" in _reviewer_), _reviewer_
    _raw_ = (
        "import socket,struct;"
        f"s=socket.socket(socket.AF_UNIX);s.connect({_socket_!r});"
        "b=b'{\"mode\":\"worker-bundle\",\"command\":[\"b2\",\"late-bundle\",\"main\"],\"folder\":\"/\",\"environment\":{}}';"
        "socket.send_fds(s,[struct.pack('>I',len(b))+b],[0,1,2]);print(s.recv(9999).decode())"
    )
    _wrongRef_ = machine.succeed(asUser(f"python3 -c {shlex.quote(_raw_)}"))
    assert ("requested ref is worker/b2/late-bundle" in _wrongRef_), _wrongRef_
    machine.succeed(start("--branch b1 --name foreign-bundle", "true", project="~/group/project"))
    _foreign_ = machine.fail(_ask_("b1/foreign-bundle", "/tmp/foreign.bundle") + " 2>&1")
    assert ("no worker alpha/b1/foreign-bundle" in _foreign_), _foreign_

    ## Step 4. Unknown project tips still use known ancestors, while no shared commit refuses
    machine.succeed(start("--branch b2 --name absent-tip", f"echo absent > absent-file;git add absent-file;{_commit_} -m absent"))
    machine.succeed(start("--branch b2 --name advanced-base", f"echo advanced > advanced-file;git add advanced-file;{_commit_} -m advanced"))
    machine.succeed(
        asUser(
            "git -C ~/alpha checkout -q -b project-only main;"
            "git -C ~/alpha -c user.name=t -c user.email=t@t commit --allow-empty -q -m project-only;"
            "git -C ~/alpha checkout -q main"
        )
    )
    machine.succeed(_ask_("b2/absent-tip", "/tmp/absent.bundle"))
    assert (int(machine.succeed("stat -c %s /tmp/absent.bundle")) < 65536)
    _absentHead_ = machine.succeed(asUser(f"git -C {folders}/alpha/b2/absent-tip/repo rev-parse worker/b2/absent-tip")).strip()
    assert (machine.succeed("git bundle list-heads /tmp/absent.bundle").split() == [_absentHead_, "refs/heads/worker/b2/absent-tip"])
    machine.succeed(
        asUser(
            f"git -C {_managerRepo_} fetch -q /tmp/absent.bundle worker/b2/absent-tip:refs/workers/b2/absent-tip;"
            f"git -C {_managerRepo_} checkout -q b2;"
            f"git -C {_managerRepo_} -c user.name=t -c user.email=t@t merge -q --no-edit refs/workers/b2/absent-tip;"
            f"test $(cat {_managerRepo_}/absent-file) = absent"
        )
    )
    machine.succeed(
        asUser(
            "git -C ~/alpha checkout -q b2;"
            "git -C ~/alpha -c user.name=t -c user.email=t@t commit --allow-empty -q -m project-new;"
            "git -C ~/alpha checkout -q main"
        )
    )
    machine.succeed(_ask_("b2/advanced-base", "/tmp/advanced.bundle"))
    assert (int(machine.succeed("stat -c %s /tmp/advanced.bundle")) < 65536)
    _advancedHead_ = machine.succeed(asUser(f"git -C {folders}/alpha/b2/advanced-base/repo rev-parse worker/b2/advanced-base")).strip()
    assert (machine.succeed("git bundle list-heads /tmp/advanced.bundle").split() == [_advancedHead_, "refs/heads/worker/b2/advanced-base"])
    machine.succeed(
        asUser(
            f"git -C {_managerRepo_} fetch -q /tmp/advanced.bundle worker/b2/advanced-base:refs/workers/b2/advanced-base;"
            f"git -C {_managerRepo_} checkout -q b2;"
            f"git -C {_managerRepo_} -c user.name=t -c user.email=t@t merge -q --no-edit refs/workers/b2/advanced-base;"
            f"test $(cat {_managerRepo_}/advanced-file) = advanced"
        )
    )
    machine.succeed(start("--branch b2 --name no-common", "true"))
    _noCommonRepo_ = f"{folders}/alpha/b2/no-common/repo"
    machine.succeed(
        asUser(
            f"find {_noCommonRepo_} -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +;"
            f"git -C {_noCommonRepo_} init -q -b worker/b2/no-common;"
            f"git -C {_noCommonRepo_} -c user.name=t -c user.email=t@t commit --allow-empty -q -m unrelated"
        )
    )
    _noCommon_ = machine.fail(_ask_("b2/no-common", "/tmp/no-common.bundle") + " 2>&1")
    assert ("shares no commit with the user's project" in _noCommon_), _noCommon_

    ## Step 5. Stream exactly the configured limit before refusing an oversized bundle
    _large_ = f"git fetch -q origin b2;head -c 2097152 /dev/urandom > large;git add large;{_commit_} -m large"
    machine.succeed(start("--branch b2 --name late-bundle", _large_))
    _oversize_ = machine.fail(_ask_("b2/late-bundle", "/tmp/large.bundle") + " 2>&1")
    assert ("1048576 bytes" in _oversize_), _oversize_
    assert (machine.succeed("stat -c %s /tmp/large.bundle").strip() == "1048576")

    ## Step 6. Exchange repo for a foreign link while bundling; only the checked repo or a refusal is allowed
    machine.succeed(start("--branch b2 --name link-bundle", f"{_commit_} --allow-empty -m checked"))
    _repo_ = f"{folders}/alpha/b2/link-bundle/repo"
    _checked_ = machine.succeed(asUser(f"git -C {_repo_} rev-parse HEAD")).strip()
    _foreignHead_ = machine.succeed(
        asUser(
            f"cp -a {_repo_} ~/bundle-target;"
            "git -C ~/bundle-target -c user.name=t -c user.email=t@t commit --allow-empty -q -m foreign;"
            "git -C ~/bundle-target rev-parse HEAD"
        )
    ).strip()
    machine.succeed(
        f"rm -f /tmp/bundle-swap-stop;(: > /tmp/bundle-swap-start;while [ ! -e /tmp/bundle-swap-stop ];do "
        f"mv {_repo_} {_repo_}-kept;ln -s {home}/bundle-target {_repo_};sleep .02;rm {_repo_};mv {_repo_}-kept {_repo_};sleep .02;done) "
        "> /tmp/bundle-swap.log 2>&1 < /dev/null &"
    )
    machine.wait_until_succeeds("test -e /tmp/bundle-swap-start")
    _status_, _result_ = machine.execute(_ask_("b2/link-bundle", "/tmp/link.bundle") + " 2>&1")
    machine.succeed("touch /tmp/bundle-swap-stop")
    machine.wait_until_succeeds(f"test -d {_repo_} -a ! -L {_repo_}")
    if (_status_ == 0):
        _result_ = machine.succeed("git bundle list-heads /tmp/link.bundle")
    assert (_foreignHead_ not in _result_), _result_
    assert ((_checked_ in _result_) or ("refused:" in _result_)), _result_

    ## Step 7. End the manager after every same-session request has completed
    openGate("alpha/manager/bundle-manager", "bundle-stop")
    sandboxEnded("alpha/manager/bundle-manager")
