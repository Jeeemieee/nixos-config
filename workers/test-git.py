import json
import re
import shlex

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


def start(options, script, project="~/alpha", launcher="worker-shell"):
    """Run a script in a sandbox started in a project with the launcher's options"""
    return asUser(implementerOf(options, project) + f"cd {project} && {launcher} {options} -c {shlex.quote(script)}")


def implementer(name, script, branch="b1"):
    return start(f"--branch {branch} --name {name}", script)


def manager(script):
    return start("--role manager", script)


def bundle(worker):
    """Receive one worker branch through the manager's broker"""
    branch, name = worker.split("/")
    path = f"$WORKER_SCRATCH/{branch}-{name}.bundle"
    return f"worker-bundle {worker} > {path} && git fetch -q {path} worker/{worker}:refs/workers/{worker}"


def tip(branch="main"):
    return machine.succeed(asUser(f"git -C ~/alpha rev-parse {branch}")).strip()


machine.start()
machine.wait_for_unit("multi-user.target")
machine.wait_for_unit("user@1000.service")
# Inside a Nix build on a host without hardware virtualisation this machine is emulated, and many times slower. Nothing here
# waits a fixed time for another side to be ready: it waits for the condition. What is measured in seconds has more room on an
# emulated machine, while on a machine with hardware virtualisation every bound is as tight as it was
emulated = machine.succeed("systemd-detect-virt").strip() != "kvm"
pace = 10 if emulated else 1
print("emulated:", emulated, "pace:", pace)
repository = 'git init -q -b main {0} && echo base > {0}/base && git -C {0} add . && git -C {0} commit -q -m base && git -C {0} branch b1'
machine.succeed(
    asUser(
        "mkdir -p ~/.config/git ~/.ssh ~/repos && echo secret > ~/.ssh/id_test && printf '[user]\\n\\tname = The User\\n\\temail = user@example.org\\n' > ~/.config/git/config && "
        + repository.format("~/alpha")
        + " && mkdir -p ~/outside ~/repos/guarded/guarded ~/repos/guarded/nested/deep && echo outside-content > ~/outside/marker && echo rule > ~/repos/guarded/guarded/file"
        " && echo deep-rule > ~/repos/guarded/nested/deep/file && echo beside > ~/repos/guarded/nested/beside && echo text > ~/repos/guarded/ordinary && git init -q -b main ~/repos/guarded"
        " && git -C ~/repos/guarded add . && git -C ~/repos/guarded commit -q -m base && git -C ~/repos/guarded branch b1"
    )
)

with subtest("V10: an implementer has its own copy on its own branch, and can only read the project's history"):
    probe = (
        'git branch --show-current; cat base; touch ~/alpha/x 2>/dev/null; echo "project-write=$?"; touch ~/alpha/.git/x 2>/dev/null; echo "history-write=$?";'
        ' git push -q origin HEAD 2>/dev/null; echo "push=$?"; git fetch -q origin; echo "fetch=$?"; ls ~/workers/alpha ~/workers/alpha/b1'
    )
    out = machine.succeed(implementer("i1", probe))
    print("V10:", out)
    assert out.splitlines()[:2] == ["worker/b1/i1", "base"] and "project-write=1" in out and "history-write=1" in out and "fetch=0" in out, out
    assert "push=0" not in out and out.rstrip().endswith(f"{folders}/alpha/b1:\ni1"), out
    machine.succeed(f"test ! -e {home}/alpha/x && test ! -e {home}/alpha/.git/x")
    # The copy's history is its own files: none is a second name of a file of the project
    counts = machine.succeed(f"find {folders}/alpha/b1/i1/repo/.git/objects -type f | wc -l; find {folders}/alpha/b1/i1/repo/.git/objects -type f -links +1 | wc -l").split()
    assert int(counts[0]) > 0 and counts[1] == "0", counts
    # Control: an ordinary local clone on the same file system does share its history files
    machine.succeed(asUser("git clone -q ~/alpha ~/linked"))
    assert int(machine.succeed(f"find {home}/linked/.git/objects -type f -links +1 | wc -l")) > 0

with subtest("V11: the manager merges in its own copy, the workers fetch from it, and the user takes the result uncommitted"):
    before = tip()
    machine.succeed(
        implementer("i1", "echo a > a && git add a && git commit -q -m 'add a'"),
        implementer("i2", "echo b > b && git add b && git commit -q -m 'add b'"),
    )
    merge = (
        bundle("b1/i1")
        + " && "
        + bundle("b1/i2")
        + " && git checkout -q b1 && git merge -q --no-edit refs/workers/b1/i1 && git merge -q --no-edit refs/workers/b1/i2"
        " && git checkout -q main && git merge -q --no-edit b1 && ls; pwd;"
        f' touch ~/alpha/x 2>/dev/null; echo "project-write=$?"; touch ~/alpha/.git/x 2>/dev/null; echo "history-write=$?"; touch {folders}/alpha/b1/i1/repo/x 2>/dev/null; echo "worker-write=$?";'
        " git log --all --format='%an <%ae> / %cn <%ce>' | sort -u"
    )
    out = machine.succeed(manager(merge))
    print("V11 manager:", out)
    assert out.split()[:3] == ["a", "b", "base"] and f"{folders}/alpha/manager/manager/repo" in out, out
    # No agent writes the project, the manager included (control: V10 shows the same for an implementer)
    assert "project-write=1" in out and "history-write=1" in out and "worker-write=1" in out, out
    # Every commit carries the user's identity
    assert out.rstrip().endswith("worker-write=1\nThe User <user@example.org> / The User <user@example.org>"), out
    assert tip() == before and tip("b1") == before

    # The implementers fetch the merged branch, and what the manager published of another worker, from the manager's copy
    out = machine.succeed(implementer("i1", "git fetch -q manager && git merge -q --no-edit manager/b1 && ls && git remote"))
    assert out.split() == ["a", "b", "base", "manager", "origin"], out
    out = machine.succeed(implementer("i2", "git fetch -q manager refs/workers/b1/i1 && git log --format=%s -1 FETCH_HEAD"))
    assert out.strip() == "add a", out

    # The user's command: refused on a side branch and with changes of his own; then staged and not committed
    machine.succeed(asUser("git -C ~/alpha checkout -q b1"))
    assert "is not on its main branch" in machine.fail(asUser("cd ~/alpha && workers take") + " 2>&1")
    machine.succeed(asUser("git -C ~/alpha checkout -q main && echo mine > ~/alpha/mine"))
    assert "has uncommitted changes" in machine.fail(asUser("cd ~/alpha && workers take") + " 2>&1")
    machine.succeed(asUser("rm ~/alpha/mine"))
    out = machine.succeed(asUser("cd ~/alpha && workers take && git status --porcelain") + " 2>&1")
    print("V11 take:", out)
    assert "staged and not committed" in out and out.rstrip().endswith("A  a\nA  b"), out
    assert tip() == before
    # Finding 5: what git proposes as the message of the user's commit holds nothing of the copies
    proposed = machine.succeed(asUser("cd ~/alpha && GIT_EDITOR=cat git commit 2>&1; true"))
    print("the proposed message:", proposed)
    assert "Squashed commit" not in proposed and "Merge" not in proposed and "add a" not in proposed and "workers/" not in proposed, proposed
    # Control: the same squash by hand, in a throwaway clone, proposes every commit of the manager's copy
    plain = machine.succeed(asUser(f"git clone -q ~/alpha ~/by-hand && cd ~/by-hand && git fetch -q file://{folders}/alpha/manager/manager/repo main && git merge -q --squash FETCH_HEAD > /dev/null && GIT_EDITOR=cat git commit 2>&1; true"))
    assert "Squashed commit of the following" in plain and "refs/workers/b1/i2" in plain and "add a" in plain, plain
    # The user commits; the main branch's history then holds his commits and no other, and no name of a worker
    machine.succeed(asUser("cd ~/alpha && git commit -q -m 'The boundary work'"))
    history = machine.succeed(asUser("git -C ~/alpha log main --format='%an|%cn|%s'")).strip().splitlines()
    print("V11 history of main:", history)
    assert history == ["The User|The User|The boundary work", "The User|The User|base"], history
    # A second round: the manager takes the user's commit into its copy, merges new work, and only the new work is staged
    machine.succeed(
        implementer("i1", "echo c > c && git add c && git commit -q -m 'add c'"),
        manager("git fetch -q origin && git merge -q --no-edit origin/main && " + bundle("b1/i1") + " && git merge -q --no-edit refs/workers/b1/i1"),
    )
    out = machine.succeed(asUser("cd ~/alpha && workers take > /dev/null 2>&1; git status --porcelain"))
    assert out.strip() == "A  c", out
    machine.succeed(asUser("cd ~/alpha && git commit -q -m 'More boundary work' && workers take") + " | grep -q 'holds nothing that the project does not have'")

    # Work that does not fit onto the user's own commits: said so, and undone with one command
    machine.succeed(
        asUser("cd ~/alpha && echo by-the-user > a && git commit -q -a -m 'My own change'"),
        implementer("i1", "echo by-the-worker > a && git commit -q -a -m 'change a'"),
        manager(bundle("b1/i1") + " && git merge -q --no-edit refs/workers/b1/i1"),
    )
    out = machine.fail(asUser("cd ~/alpha && workers take") + " 2>&1")
    assert "does not fit onto main without conflicts" in out, out
    machine.succeed(asUser("cd ~/alpha && git reset -q --hard && test -z \"$(git status --porcelain)\" && grep -qx by-the-user a"))
    # The manager takes the user's commit into its copy and settles the conflict there; then the result fits
    machine.succeed(manager("git fetch -q origin && (git merge -q --no-edit origin/main || (echo settled > a && git commit -q -a -m settle))"))
    assert machine.succeed(asUser("cd ~/alpha && workers take > /dev/null 2>&1; git status --porcelain")).strip() == "M  a"
    machine.succeed(asUser("cd ~/alpha && git commit -q -m 'Settled'"))

with subtest("R12: a taken manager is removable, with a later commit and a sent-back take as controls"):
    machine.succeed(asUser("git init -q -b main ~/taken && echo base > ~/taken/base && git -C ~/taken add . && git -C ~/taken commit -q -m base && git -C ~/taken branch b1"))
    takenManager = lambda script: start("--role manager", script, project="~/taken")
    machine.succeed(
        takenManager(
            "git checkout -q main && echo main > main-work && git add main-work && git commit -q -m main-work"
            " && git checkout -q b1 && echo side > side-work && git add side-work && git commit -q -m side-work && git checkout -q main"
        )
    )
    machine.succeed(
        asUser("cd ~/taken && workers take > /dev/null && git commit -q -m taken-main && workers take --branch b1 > /dev/null && git commit -q -m taken-side && git switch -q main")
    )
    _, taken = machine.execute(asUser("workers remove taken/manager/manager") + " 2>&1")
    machine.succeed(takenManager("git checkout -q main && echo later > later && git add later && git commit -q -m later"))
    later = machine.fail(asUser("workers remove taken/manager/manager") + " 2>&1")
    machine.succeed(asUser("cd ~/taken && workers take > /dev/null && git commit -q -m taken-later && git reset -q --hard HEAD^"))
    sentBack = machine.fail(asUser("workers remove taken/manager/manager") + " 2>&1")
    print("R12 taken:", taken.strip(), "| later:", later.strip(), "| sent back:", sentBack.strip())
    assert "plain folders on this machine" in taken, taken
    assert "commit(s) that neither the project nor a manager's copy holds" in later, later
    assert "commit(s) that neither the project nor a manager's copy holds" in sentBack, sentBack

with subtest("Every reserved side-branch name is refused"):
    reserved = {}
    for branch in ["manager", "archive", "instructions", "plain", "old"]:
        _, reserved[branch] = machine.execute(asUser(f"cd ~/alpha && workers take --branch {branch}") + " 2>&1")
    print("reserved branches for workers take:", reserved)
    assert all("cannot be a branch name" in reserved[branch] for branch in reserved), reserved

with subtest("workers list, and a removal's checks"):
    out = machine.succeed(asUser("workers list"))
    print("workers list:", out)
    rows = {tuple(line.split()[:3]): line.split() for line in out.strip().splitlines()[1:]}
    assert rows[("alpha", "b1", "i1")][3:5] == ["implementer", "stopped"] and rows[("alpha", "b1", "i1")][-1] == "0", out
    assert rows[("alpha", "b1", "i2")][-1] == "0" and rows[("alpha", "manager", "manager")][3] == "manager", out
    # Uncommitted changes, and commits that nobody else holds
    machine.succeed(implementer("i2", "echo draft > draft"))
    assert "has uncommitted changes" in machine.fail(asUser("workers remove alpha/b1/i2") + " 2>&1")
    machine.succeed(implementer("i2", "git add draft && git commit -q -m draft"))
    out = machine.fail(asUser("workers remove alpha/b1/i2") + " 2>&1")
    assert "has 1 commit(s) that neither the project nor a manager's copy holds" in out, out
    assert machine.succeed(asUser("workers list")).count(" 1\n") == 1
    # Here the workers are plain folders: a merged, clean worker passes the checks and is then refused for that reason
    assert "plain folders on this machine" in machine.fail(asUser("workers remove alpha/b1/i1") + " 2>&1")
    for wrong in ["alpha/b1", "alpha/b1/../i1", "alpha/b1/nobody", "'alpha/b1/i1 x'"]:
        machine.fail(asUser(f"workers remove {wrong}"))

with subtest("V12: a copy with planted hooks and settings runs nothing outside a sandbox"):
    plant = r'''
m=$WORKER_SCRATCH/marker.sh
printf '#!/bin/sh\necho ran >> /tmp/planted-ran\necho ran >> %s/planted-ran 2>/dev/null\nexit 0\n' "$WORKER_SCRATCH" > $m; chmod +x $m
for hook in applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge pre-push pre-receive update proc-receive post-receive post-update reference-transaction push-to-checkout pre-auto-gc post-rewrite sendemail-validate fsmonitor-watchman post-index-change; do cp $m .git/hooks/$hook; done
for setting in core.fsmonitor core.pager core.editor core.sshCommand core.alternateRefsCommand uploadpack.packObjectsHook diff.external credential.helper; do git config $setting $m; done
for kind in clean smudge process; do git config filter.planted.$kind $m; done
git config core.hooksPath $PWD/.git/hooks
echo '* filter=planted' > .gitattributes
echo change > planted-change; git add . > /dev/null 2>&1; git commit -q -m planted > /dev/null 2>&1
rm -f /tmp/planted-ran $WORKER_SCRATCH/planted-ran
git status > /dev/null 2>&1
test -e /tmp/planted-ran && echo control=ran-inside
'''
    # Control: inside the worker's own sandbox the planted program does run
    out = machine.succeed(implementer("i3", plant))
    assert "control=ran-inside" in out, out
    machine.succeed(f"test -s {areas}/alpha/b1/i3/planted-ran && rm {areas}/alpha/b1/i3/planted-ran && ! test -e /tmp/planted-ran")

    def outside(label):
        """Everything of this design that touches the copy from outside its sandbox"""
        machine.succeed(asUser("workers list") + " > /tmp/list 2>&1", asUser("workers remove alpha/b1/i3; true") + " > /tmp/remove 2>&1")
        # A queued run, whose record takes the copy's commit; and the manager's bundle and fetch inside its sandbox
        machine.succeed(implementer("i3", "queue run -- true; rm -f $WORKER_SCRATCH/planted-ran"))
        fetched = machine.succeed(manager(bundle("b1/i3") + ' 2>&1; echo "fetch=$?"; test -e /tmp/planted-ran && echo ran-in-the-manager; true'))
        record = json.loads(machine.succeed(f"tail -n 1 {folders}/alpha/b1/i3/records/runs.jsonl"))
        print(f"V12 {label}:", machine.succeed("grep ' i3 ' /tmp/list; cat /tmp/remove").strip(), "| record commit:", record["commit"], "|", fetched.strip())
        machine.succeed(f"! test -e /tmp/planted-ran && ! test -e {areas}/alpha/b1/i3/planted-ran")
        assert "ran-in-the-manager" not in fetched, fetched
        return record

    record = outside("hooks and settings")
    assert record["commit"] == machine.succeed(implementer("i3", "git rev-parse HEAD 2>/dev/null")).strip() and record["uncommitted_as_reported"] in ("yes", "no"), record
    # The copy's .git renamed away and made anew with a planted setting; then a link in its place; then a commondir file that names a prepared folder
    variants = {
        ".git made anew": "mv .git .git-old && git init -q -b other . && git config core.fsmonitor $WORKER_SCRATCH/marker.sh && git commit -q --allow-empty -m anew",
        ".git as a link": "rm -rf .git && mv .git-old real-git && ln -s real-git .git",
        "a commondir file": "rm .git && mv real-git .git && mkdir -p prepared && cp -r .git/config .git/hooks prepared/ && echo ../prepared > .git/commondir",
    }
    for label, change in variants.items():
        machine.succeed(implementer("i3", change + "; true"))
        outside(label)

with subtest("Finding 6: the preparation step and the question about uncommitted changes run within the workers' limits"):
    # The preparation of a worker's copy, seen while it runs
    machine.succeed(f"( ({start('--branch b1 --name s1', 'true', launcher='worker-shell-slow')}) > /dev/null 2>&1; touch /tmp/s1-ended ) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(asUser("systemctl --user is-active --quiet prepare-worker:alpha:b1:s1.scope"), timeout=20 * pace)
    group = machine.succeed(asUser("systemctl --user show -p Slice -p MemoryMax -p MemorySwapMax prepare-worker:alpha:b1:s1.scope"))
    print("preparation:", group)
    assert "Slice=workers-agents.slice" in group and "MemoryMax=536870912" in group and "MemorySwapMax=0" in group, group
    machine.wait_until_succeeds(f"test -e {folders}/alpha/b1/s1/repo/.git", timeout=30 * pace)
    # The start has ended when the command that made it has
    machine.wait_until_succeeds("test -e /tmp/s1-ended", timeout=60 * pace)
    machine.wait_until_succeeds(asUser("! systemctl --user is-active --quiet worker:alpha:b1:s1.scope"), timeout=30 * pace)
    # The question, with a program in the copy's settings that never ends and ignores a polite stop. Control first: without it the answer comes at once
    assert "plain folders on this machine" in machine.fail(asUser("workers remove alpha/b1/s1") + " 2>&1")
    hang = 'printf \'#!%s\ntrap "" TERM\nwhile :; do :; done\n\' "$(readlink -f "$(command -v bash)")" > never.sh; chmod +x never.sh; git add never.sh; git commit -q -m never; git config core.fsmonitor "$PWD/never.sh"'
    machine.succeed(implementer("s1", hang + "; true"))
    # (this machine gives the question 15 seconds, and 5 more to a program that ignores the polite stop)
    status, out = machine.execute(f"timeout {60 * pace} " + asUser("SECONDS=0; workers remove alpha/b1/s1; echo \"status=$? after $SECONDS s\"") + " 2>&1")
    print("the question with a program that never ends:", out)
    assert status == 0 and "git cannot read it (?)" in out and "status=2" in out and 15 <= int(out.rstrip().split()[-2]) < (30 + 3 * pace if emulated else 30), out
    machine.fail("pgrep -f never.sh")

with subtest("A copy of a repository with protected files keeps them read-only, unless the session is unlocked"):
    probe = 'echo x >> guarded/file 2>/dev/null; echo "guarded=$?"; echo new > guarded/new 2>/dev/null; echo "new=$?"; echo x >> ordinary; echo "ordinary=$?"'
    for options in ["--branch b1 --name p1", "--role manager"]:
        out = machine.succeed(start(options, probe, project="~/repos/guarded", launcher="worker-shell-guarded"))
        assert out.split() == ["guarded=1", "new=1", "ordinary=0"], f"{options}: {out}"
    out = machine.succeed(start("--unlock --branch b1 --name p1", probe, project="~/repos/guarded", launcher="worker-shell-guarded") + " 2>&1")
    print("protected copy, unlocked:", out)
    assert "unlocked for this session" in out and out.split()[-3:] == ["guarded=0", "new=0", "ordinary=0"], out
    # Control: the same launcher in a project without protected files
    assert "guarded" not in machine.succeed(start("--branch b1 --name i1", "echo ok", launcher="worker-shell-guarded"))

with subtest("Point 1 of the review: what an ordinary session has read-only in its project, its queued jobs have read-only too"):
    # The mounts are named by path in the view and opened anew for every job, by the same program as for the agent
    machine.succeed(asUser("cd ~/repos/guarded && git checkout -q -- . && git status --porcelain | wc -l | grep -qx 0"))
    attempt = (
        "for target in .git/hooks/planted guarded/file nested/deep/file; do if { echo change >> $target; } 2>/dev/null; then echo \"$target=accepted\"; else echo \"$target=refused\"; fi; done;"
        " if mv nested nested.away 2>/dev/null; then echo rename=accepted; else echo rename=refused; fi;"
        " if { echo change >> nested/beside; } 2>/dev/null; then echo beside=accepted; else echo beside=refused; fi"
    )
    expected = [".git/hooks/planted=refused", "guarded/file=refused", "nested/deep/file=refused", "rename=refused", "beside=accepted"]
    for label, command in [("the agent", attempt), ("a job", f"queue run -- bash -c {shlex.quote(attempt)}")]:
        out = machine.succeed(start("", command, project="~/repos/guarded", launcher="worker-shell-guarded") + " 2>&1")
        print(f"an ordinary session in a repository with protected files, {label}:", out)
        assert out.split() == expected, f"{label}: {out}"
    # Control: with --unlock the protected files can be changed in a job as by the agent; .git stays read-only
    out = machine.succeed(start("--unlock", f"queue run -- bash -c {shlex.quote(attempt)}", project="~/repos/guarded", launcher="worker-shell-guarded") + " 2>/dev/null")
    # (after the rename there is no nested/beside to change)
    assert out.split() == [".git/hooks/planted=refused", "guarded/file=accepted", "nested/deep/file=accepted", "rename=accepted", "beside=refused"], out
    machine.succeed(asUser("cd ~/repos/guarded && rm -rf nested && mv nested.away nested && git checkout -q -- . && test ! -e .git/hooks/planted"))

with subtest("Instruction 6: the folders above a protected path in a copy can be neither renamed nor replaced, and a link in their place stops the start"):
    guarded = lambda options, script: start(options, script, project="~/repos/guarded", launcher="worker-shell-guarded")
    attempt = (
        "if mv nested nested.away 2>/dev/null && mkdir -p nested/deep && echo replaced > nested/deep/file; then echo parent-replace=accepted; else echo parent-replace=refused; fi;"
        " if mv nested/deep nested/deep.away 2>/dev/null; then echo inner-rename=accepted; else echo inner-rename=refused; fi;"
        " if echo change >> nested/deep/file 2>/dev/null; then echo file-change=accepted; else echo file-change=refused; fi;"
        " if echo change >> nested/beside; then echo beside-change=accepted; else echo beside-change=refused; fi;"
        " cat nested/deep/file"
    )
    expected = ["parent-replace=refused", "inner-rename=refused", "file-change=refused", "beside-change=accepted", "deep-rule"]
    # The agent itself; then a job, whose sandbox is made anew from the same view
    out = machine.succeed(guarded("--branch b1 --name p2", attempt))
    print("the folders above a protected path, the agent:", out)
    assert out.split() == expected, out
    out = machine.succeed(guarded("--branch b1 --name p2", f"queue run -- bash -c {shlex.quote(attempt)}"))
    print("the folders above a protected path, a job:", out)
    assert out.split() == expected, out
    copy = f"{folders}/guarded/b1/p2/repo"
    assert machine.succeed(f"cat {copy}/nested/deep/file {copy}/nested/beside; ls {copy}").split() == ["deep-rule", "beside", "change", "change", "guarded", "nested", "ordinary"]
    # Control: in an unlocked session the same exchange is accepted, so the refusals above are the mounts
    out = machine.succeed(guarded("--unlock --branch b1 --name p3", attempt + " 2>/dev/null; true") + " 2>&1")
    assert "parent-replace=accepted" in out and "inner-rename=accepted" in out, out
    assert machine.succeed(f"cat {folders}/guarded/b1/p3/repo/nested/deep.away/file").strip() == "replaced"

    # A link where a folder above a protected path was, or where the path itself was, made in unlocked sessions. It leads to a
    # folder outside the worker's view that holds the same names, so that only the link itself can give it away
    machine.succeed(
        asUser("mkdir -p ~/outside/deep && echo outside-content > ~/outside/deep/file"),
        guarded("--unlock --branch b1 --name p3", f"rm -rf nested nested.away && ln -s {home}/outside nested"),
        guarded("--unlock --branch b1 --name p4", f"rm nested/deep/file && ln -s {home}/outside/marker nested/deep/file"),
    )
    out = machine.fail(guarded("--branch b1 --name p3", "cat nested/deep/file") + " 2>&1")
    print("a link above a protected path:", out)
    assert f"refusing: {folders}/guarded/b1/p3/repo/nested is a link, which cannot be protected" in out and "outside-content" not in out, out
    out = machine.fail(guarded("--branch b1 --name p4", "cat nested/deep/file") + " 2>&1")
    assert "its protected nested/deep/file is a link, which cannot be protected" in out and "outside-content" not in out, out
    # The same exchange made after the launcher looked is met by the program that opens the paths for bwrap, here run by hand
    opener = machine.succeed("grep -o '/nix/store/[^ ]*/bin/python3 -I /nix/store/[^ ]*-open-checked.py' $(readlink -f $(command -v worker-shell-guarded)) | head -n 1").strip()
    opened = lambda name, option, path: asUser(f"{opener} echo {option} {folders}/guarded/b1/{name}/repo {path} /destination -- {option} untouched")
    for name, option, path in [("p3", "--bind-checked", "nested"), ("p3", "--ro-bind-checked", "nested/deep/file"), ("p4", "--ro-bind-checked", "nested/deep/file")]:
        out = machine.fail(opened(name, option, path) + " 2>&1")
        assert "is missing or is reached through a link, so the sandbox does not start" in out and "destination" not in out, out
    # Control: real paths are opened and handed on as descriptors; what follows -- is left as it is
    out = machine.succeed(opened("p2", "--bind-checked", "nested") + "; " + opened("p2", "--ro-bind-checked", "nested/deep/file"))
    print("opened by hand:", out)
    words = out.split()
    assert words[0] == "--bind-fd" and words[1].isdigit() and words[2:6] == ["/destination", "--", "--bind-checked", "untouched"] and words[6] == "--ro-bind-fd" and words[10:] == ["--ro-bind-checked", "untouched"], out

with subtest("B7, first part: a job beyond the time limit of its mode is stopped, and its record says so"):
    # This machine stops timing jobs after 10 seconds; jobs of the other modes have no limit
    script = 's=$SECONDS; queue timing -- bash -c "echo began; sleep 300; echo finished"; echo "exit=$? after $((SECONDS - s)) s"; queue run -- bash -c "sleep 12; echo control-finished"; echo "control=$?"'
    out = machine.succeed(implementer("t1", script) + " 2>&1")
    print("time limit:", out)
    lines = out.strip().splitlines()
    assert lines[0] == "began" and "finished" not in lines and "queue: the job was stopped after 10 seconds, the time limit of 'timing' jobs on this machine" in lines, out
    # Stopped at the limit, give or take a second; an emulated machine needs longer to start and to end a job, and gets up to 20 more
    took = [line for line in lines if line.startswith("exit=")][0]
    assert took.startswith("exit=143 after ") and 10 <= int(took.split()[2]) <= (30 if emulated else 11) and lines[-2:] == ["control-finished", "control=0"], out
    entries = [json.loads(line) for line in machine.succeed(f"tail -n 4 {folders}/alpha/b1/t1/records/runs.jsonl").splitlines()]
    print("time limit, records:", entries)
    assert entries[0]["state"] == "started" and entries[1]["id"] == entries[0]["id"] and "state" not in entries[1], entries
    assert (entries[1]["mode"], entries[1]["time_limit"], entries[1]["stopped"], entries[1]["exit"]) == ("timing", True, True, 143), entries
    assert (entries[3]["mode"], entries[3]["time_limit"], entries[3]["stopped"], entries[3]["exit"]) == ("run", False, False, 0), entries
    machine.fail("pgrep -x -f 'sleep 300'")

with subtest("workers take --branch: a side branch that the manager prepared arrives as one staged change, for the user's commit"):
    refs = lambda: machine.succeed(asUser("cd ~/alpha && git for-each-ref --format='%(refname) %(objectname)'; git symbolic-ref --short HEAD; git status --porcelain"))
    # Control: the project has no branch of that name, so no worker can be started on it
    assert "has no branch 'side1'" in machine.fail(implementer("s9", "true", branch="side1") + " 2>&1")
    # The manager takes the project's commits into its copy and prepares the branch there, from the main branch, with two commits
    machine.succeed(manager("git fetch -q origin && git checkout -q main && git merge -q --no-edit origin/main && git checkout -q -b side1 main && echo one > s1 && git add s1 && git commit -q -m 'sorted: one' && echo two > s2 && git add s2 && git commit -q -m 'sorted: two' && git checkout -q main"))
    # What is refused, each with its message and without a change to any branch, to the current branch or to the working tree
    before = refs()
    refusals = [
        ("--branch main", "is the project's main branch: that is 'workers take' without --branch"),
        ("--branch 'a b'", "is not a branch name that workers can have"),
        ("--branch archive", "cannot be a branch name"),
        ("--branch nope", "the branch 'nope' of the manager's copy could not be fetched"),
        ("--branch side1 nobody", "the manager 'nobody' of alpha has no copy"),
    ]
    for options, reason in refusals:
        out = machine.fail(asUser(f"cd ~/alpha && workers take {options}") + " 2>&1")
        assert reason in out, f"{options}: {out}"
    machine.succeed(asUser("echo mine > ~/alpha/mine"))
    assert "has uncommitted changes" in machine.fail(asUser("cd ~/alpha && workers take --branch side1") + " 2>&1")
    machine.succeed(asUser("rm ~/alpha/mine"))
    assert refs() == before, (before, refs())
    # Taken: the project is on the new branch, which starts at the main branch's commit; the manager's two commits are one staged change
    out = machine.succeed(asUser("cd ~/alpha && workers take --branch side1 && git symbolic-ref --short HEAD && git status --porcelain && git rev-list --count main..side1") + " 2>&1")
    print("take --branch:", out)
    assert "staged on the new branch 'side1' and not committed" in out and out.split()[-6:] == ["side1", "A", "s1", "A", "s2", "0"], out
    proposed = machine.succeed(asUser("cd ~/alpha && GIT_EDITOR=cat git commit 2>&1; true"))
    assert "Squashed commit" not in proposed and "sorted:" not in proposed, proposed
    # The user commits: the branch's history in the project holds his commit and none of the copy's
    machine.succeed(asUser("cd ~/alpha && git commit -q -m 'The sorted work' && git switch -q main"))
    history = machine.succeed(asUser("git -C ~/alpha log main..side1 --format='%an|%s'")).strip().splitlines()
    assert history == ["The User|The sorted work"], history
    # An implementer can now be started on the branch, and its copy holds the taken work
    assert machine.succeed(implementer("s9", "cat s1 s2", branch="side1")).split() == ["one", "two"]
    # A second round: the manager takes the user's commit into its branch and adds to it; only the addition is staged, on the
    # branch, which the tool enters from the main branch
    machine.succeed(manager("git fetch -q origin && git checkout -q side1 && git merge -q --no-edit origin/side1 && echo three > s3 && git add s3 && git commit -q -m 'sorted: three' && git checkout -q main"))
    out = machine.succeed(asUser("cd ~/alpha && workers take --branch side1 && git symbolic-ref --short HEAD && git status --porcelain") + " 2>&1")
    assert "staged on the branch 'side1' and not committed" in out and out.split()[-3:] == ["side1", "A", "s3"], out
    machine.succeed(asUser("cd ~/alpha && git commit -q -m 'More sorted work' && git switch -q main"))
    # Nothing new: said so, and the project is where it was. The same for a branch of the manager's that adds nothing: no branch is made
    before = refs()
    assert "holds nothing that the project does not have" in machine.succeed(asUser("cd ~/alpha && workers take --branch side1"))
    machine.succeed(manager("git branch empty main"))
    assert "holds nothing that the project does not have" in machine.succeed(asUser("cd ~/alpha && workers take --branch empty"))
    assert refs() == before, (before, refs())
    # Undone with the command that the tool names: the project is on the main branch again, clean, and the new branch is gone
    machine.succeed(manager("git checkout -q -b side2 main && echo four > s4 && git add s4 && git commit -q -m 'sorted: four' && git checkout -q main"))
    out = machine.succeed(asUser("cd ~/alpha && workers take --branch side2"))
    assert "send it back with 'git reset --hard && git switch main && git branch -D side2'" in out, out
    machine.succeed(asUser("cd ~/alpha && git reset -q --hard && git switch -q main && git branch -q -D side2"))
    assert refs() == before, (before, refs())

with subtest("workers found: the work that is not committed is kept on a branch of its own, and nothing of the project is changed"):
    machine.succeed(
        asUser(
            "git init -q -b main ~/old && cd ~/old && echo base > tracked && echo 'ignored-*' > .gitignore && git add . && git commit -q -m base"
            " && echo stashed > in-a-stash && git add in-a-stash && git stash -q"
            " && echo changed >> tracked && echo new > untracked && echo staged > staged && git add staged && echo output > ignored-output && head -c 2M /dev/zero > large"
        )
    )
    # (git may bring its index up to date once when it is first asked for the status; after that the file stays as it is)
    machine.succeed("sleep 2", asUser("git -C ~/old status > /dev/null"))
    state = lambda: machine.succeed(asUser("cd ~/old && sha256sum .git/index && git status --porcelain --ignored && git symbolic-ref HEAD && git rev-parse HEAD && git stash list"))
    before = state()
    out = machine.succeed(asUser("cd ~/old && workers found"))
    print("workers found:", out)
    day = machine.succeed("date +%F").strip()
    assert f"found/{day}: 3 files changed, 3 insertions(+)" in out and f"found/{day}-stash-0:" in out and "left out, larger than 1M: large" in out, out
    assert "The working tree, the index and the current branch are as they were" in out and "--allow-ro /home" in out, out
    assert state() == before, (before, state())
    # The branch holds the changed, the staged and the untracked file, as one commit of the user's on top of where he was
    shown = machine.succeed(asUser(f"cd ~/old && git diff --name-only main found/{day} && git log --format='%an|%s' main..found/{day} && git show found/{day}:tracked && git diff --name-only main found/{day}-stash-0"))
    assert shown.split("\n") == ["staged", "tracked", "untracked", f"The User|The work as found on {day}", "base", "changed", "in-a-stash", ""], shown
    # Again on the same day, now with the large file: a second branch, and the first is as it was
    first = machine.succeed(asUser(f"git -C ~/old rev-parse found/{day}"))
    out = machine.succeed(asUser("cd ~/old && workers found --with-large-files"))
    assert f"found/{day}-2: 4 files changed" in out and "left out" not in out and machine.succeed(asUser(f"git -C ~/old rev-parse found/{day}")) == first, out
    assert state() == before, (before, state())
    # Nothing uncommitted and no stash: nothing is recorded and no branch is made
    machine.succeed(asUser("git clone -q ~/old ~/old-clean"))
    out = machine.succeed(asUser("cd ~/old-clean && workers found && git branch --list 'found/*' | wc -l"))
    assert "nothing to record" in out and out.split()[-1] == "0", out
    # Where it does not run: outside a project, in a project without a commit, and in a worker's copy, which an agent writes
    assert "this is not inside a project" in machine.fail(asUser("cd ~ && workers found") + " 2>&1")
    assert "has no commit yet" in machine.fail(asUser("git init -q ~/empty && cd ~/empty && workers found") + " 2>&1")
    assert "is a worker's folder, which an agent writes" in machine.fail(asUser(f"cd {folders}/alpha/b1/i1/repo && workers found") + " 2>&1")
    # A manager started afterwards has the branch in its copy, and reads the found work there
    machine.succeed(asUser("cd ~/alpha && echo unfinished > unfinished && workers found && rm unfinished"))
    assert machine.succeed(manager(f"git fetch -q origin && git show origin/found/{day}:unfinished")).strip() == "unfinished"

with subtest("nix in a sandbox reaches the system's daemon: a session without and with the worker setup, and a queued job, each add a file to the store"):
    # The sandbox shares the daemon's socket and nothing else of /nix/var/nix. Left to itself, nix takes the folders above
    # the socket for a store of its own wherever they are writable, and fails on the read-only /nix/store
    add = 'echo "$1" > /tmp/for-the-store && nix-store --add /tmp/for-the-store'
    # Control: the same as the user, outside every sandbox, so the daemon and the store of this machine do take a file
    assert machine.succeed(asUser("echo outside > ~/for-the-store && nix-store --add ~/for-the-store")).startswith("/nix/store/")
    cases = [
        ("a session without the worker setup", start("", f"bash -c {shlex.quote(add)} bash plain", launcher="plain-shell")),
        ("an ordinary session", start("", f"bash -c {shlex.quote(add)} bash session")),
        ("its queued job", start("", f"queue run -- bash -c {shlex.quote(add)} bash job")),
    ]
    results = [(label, *machine.execute(command + " 2>&1")) for label, command in cases]
    for label, status, out in results:
        print(f"nix, {label}:", status, out)
    for label, status, out in results:
        assert status == 0 and out.strip().splitlines()[-1].startswith("/nix/store/"), (label, status, out)
