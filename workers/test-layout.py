import json
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


def worker(branch, name, script, project="alpha", locked=False):
    """Run a script in the sandbox of an implementer; locked: as a new one, without the user's approval"""
    return asUser(("" if locked else approved(project, branch, name)) + f"cd ~/{project} && worker-shell --branch {branch} --name {name} -c {shlex.quote(script)}")


# A complete intent form, for the tests of `workers approve --empty-scratch`
intent = """# Intent
## Goal
Try the scratch area.
## Changes
- none
## Not changed
Everything.
## Acceptance criteria
- The area is empty afterwards
## Tests
- none: nothing is changed
## Approach 1: Directly
### Trade-offs
None.
### Steps
- Do it
## Approach 2: Otherwise
### Trade-offs
None.
### Steps
- Do it otherwise
## Recommendation
Approach 1.
## Open questions
None.
"""


def planned(node, name):
    """A new implementer that wrote into its scratch area, ran a job, and has a complete form"""
    node.succeed(worker("b1", name, "echo draft > $WORKER_SCRATCH/draft; queue run -- echo kept-output", locked=True) + " 2>/dev/null")
    node.succeed("cat > /tmp/form <<'END-OF-THE-FORM'\n" + intent + "END-OF-THE-FORM", f"install -o {user} -m 644 /tmp/form {folders}/alpha/b1/{name}/reports/intent.md")


def approve(name, options=""):
    return asUser(f"printf '1\\n\\nyes\\n' | workers approve {options} alpha/b1/{name}") + " 2>&1"


def manager(script, project="alpha"):
    return asUser(f"cd ~/{project} && worker-shell --role manager -c {shlex.quote(script)}")


def datasets():
    return machine.succeed("zfs list -H -o name -r rpool | sort").split()


def boot():
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("user@1000.service")
    # This test starts sanoid itself, where it looks at the snapshots. The hourly timer would take one whenever the test happens
    # to run over the full hour, also while a worker's folder holds a file that a subtest made large on purpose; that snapshot
    # then keeps the folder at its limit for the subtests that follow
    machine.succeed("systemctl stop sanoid.timer")


with subtest("Plain folders: a machine without the two datasets"):
    plain.start()
    plain.wait_for_unit("multi-user.target")
    plain.wait_for_unit("user@1000.service")
    plain.succeed(asUser("mkdir ~/alpha && git -C ~/alpha init -q -b main && git -C ~/alpha -c user.name=t -c user.email=t@t commit -q --allow-empty -m base && git -C ~/alpha branch b1"))
    out = plain.succeed(worker("b1", "w1", 'pwd; echo data > $WORKER_SCRATCH/file; echo "scratch=$?"; ls ~/workers/alpha ~/workers/alpha/b1'))
    print("plain worker:", out)
    assert out.splitlines()[0] == f"{folders}/alpha/b1/w1/repo" and "scratch=0" in out, out
    plain.succeed(worker("b1", "w2", "true"))
    # The first worker sees its own folder and area, and not the second one's
    out = plain.succeed(worker("b1", "w1", f"ls ~/workers/alpha/b1 {areas}/alpha/b1"))
    assert [word for word in out.split() if not word.endswith(":")] == ["w1", "w1"], out
    plain.succeed(f"test -d {folders}/alpha/b1/w2 && test -d {areas}/alpha/b1/w2")
    # Without ZFS there is nothing to snapshot: refused with the reason
    out = plain.fail(asUser("cd ~/alpha && worker-shell --branch b1 --name w1 --snapshot before") + " 2>&1")
    print("plain snapshot:", out)
    assert "there are no snapshots" in out, out
    # W18, without the datasets: emptying a scratch area at the approval is refused with the reason, and nothing is approved
    planned(plain, "es0")
    out = plain.fail(approve("es0", "--empty-scratch"))
    assert "--empty-scratch needs the datasets" in out and "Nothing was approved" in out, out
    plain.succeed(f"test ! -e {home}/.local/state/workers/alpha/approvals/b1/es0 && grep -qx draft {areas}/alpha/b1/es0/draft")
    plain.shutdown()

machine.start()
boot()
# Inside a Nix build on a host without hardware virtualisation this machine is emulated, and many times slower. Nothing here
# waits a fixed time for another side to be ready: it waits for the condition, or the other side waits at a gate. (The lines
# "sync; sleep 6" are not such waits: they wait for ZFS, which brings its accounting up to date every five seconds)
emulated = machine.succeed("systemd-detect-virt").strip() != "kvm"
pace = 10 if emulated else 1
print("emulated:", emulated, "pace:", pace)
# The parents, created once as the laptop's layout declares them; the system imports the pool and mounts them at the next boot
machine.succeed("zpool create -O mountpoint=none -O compression=zstd rpool /dev/vdb", *create)
machine.shutdown()
machine.start()
boot()
print("PARENTS", machine.succeed("findmnt -rn -t zfs -o TARGET,SOURCE; stat -c '%n %U %a' " + f"{home}/scratch {folders} {areas}"))
for mount in mounts:
    assert mount in machine.succeed("findmnt -rn -t zfs -o TARGET,SOURCE"), mount
assert machine.succeed(f"stat -c '%U %a' {folders} {areas} {home}/scratch").split() == ["root", "755", "root", "755", user, "755"]
machine.succeed(
    asUser("mkdir -p ~/.config/git && printf '[user]\\n\\tname = The User\\n\\temail = user@example.org\\n' > ~/.config/git/config"),
    asUser("mkdir -p ~/.ssh ~/alpha && echo secret > ~/.ssh/id_test && git -C ~/alpha init -q -b main && git -C ~/alpha -c user.name=t -c user.email=t@t commit -q --allow-empty -m base && git -C ~/alpha branch b1"),
    "mkdir -p /var/lib/target && echo root-only > /var/lib/target/file",
)
helper = machine.succeed("grep -o '/nix/store/[^ ]*/bin/worker-datasets' /etc/sudoers | head -n 1").strip()
before = datasets()

with subtest("L0: the user cannot create, rename or link in the two parents (control: he can in ~/scratch)"):
    out = machine.succeed(
        asUser(
            f'mkdir {folders}/x; echo "mkdir-workers=$?"; mkdir {areas}/x; echo "mkdir-areas=$?"; ln -s /var/lib/target {folders}/evil; echo "link=$?";'
            f' mv {folders} {home}/workers.away; echo "rename-workers=$?"; mv {areas} {home}/scratch/away; echo "rename-areas=$?"; mkdir ~/scratch/own && rmdir ~/scratch/own; echo "control=$?"'
        )
        + " 2>&1"
    )
    print("L0:", out)
    for expected in ["mkdir-workers=1", "mkdir-areas=1", "link=1", "rename-workers=1", "rename-areas=1", "control=0"]:
        assert expected in out, out

with subtest("V13a: a parent that is not mounted and was replaced by the caller"):
    # As if the mount had failed at boot: the folder underneath is in the user's own ~/scratch, where he can rename it
    machine.succeed(f"umount {areas}")
    for label, replace in [
        ("link", f"mv {areas} {areas}.real && ln -s /var/lib/target {areas}"),
        ("own folder", f"rm {areas} && mkdir {areas}"),
    ]:
        machine.succeed(asUser(replace))
        out = machine.succeed(asUser(f'sudo -n {helper} ensure alpha b1 w1; echo "helper=$?"') + " 2>&1")
        print(f"V13a {label}:", out)
        assert "helper=2" in out and "refusing" in out, out
        # Through the launcher the worker does not start
        machine.fail(worker("b1", "w1", "true"))
    assert machine.succeed("ls /var/lib/target").split() == ["file"]
    assert datasets() == before, datasets()
    machine.succeed(asUser(f"rmdir {areas} && mv {areas}.real {areas}"), f"mount {areas}")

with subtest("F2: a failed mount of the workers' folders is reported on the desktop"):
    machine.succeed("systemd-run --unit=signal-monitor dbus-monitor --system \"interface='net.nuetzlich.SystemNotifications'\"")
    # A parent that is not as declared: the helper refuses, so the unit fails (restarting it with a parent unmounted would only mount the parent again)
    machine.succeed(f"chmod 777 {folders}")
    machine.fail("systemctl restart worker-datasets-mount.service")
    # The monitor may not have listened yet when that failure was reported: the failure is repeated until the monitor has seen one
    again = "systemctl reset-failed worker-datasets-mount.service; systemctl restart worker-datasets-mount.service; false"
    machine.wait_until_succeeds(f"journalctl -u signal-monitor.service --no-pager | grep -q 'not mounted' || {{ {again}; }}", timeout=60 * pace)
    print("F2:", machine.succeed("journalctl -u worker-datasets-mount.service --no-pager | grep refusing | tail -n 1; journalctl -u signal-monitor.service --no-pager | grep -c 'not mounted'"))
    machine.succeed(f"chmod 755 {folders}", "systemctl restart worker-datasets-mount.service")

with subtest("The password-less rule covers the helper and nothing else"):
    # The user is in wheel, as on the laptop: every other command asks for the password
    out = machine.succeed(asUser(f'sudo -n true; echo "other=$?"; sudo -n {helper} mount-all; echo "helper=$?"') + " 2>&1")
    print("sudo:", out)
    assert "other=1" in out and "helper=0" in out, out

with subtest("V13b: names that reach outside the two parents"):
    for arguments in ["../x b1 w1", "alpha ../x w1", "alpha b1 ..", "alpha a/b w1", "alpha archive w1", "alpha instructions w1", "alpha b1 'w 1'", "alpha b1"]:
        out = machine.succeed(asUser(f'sudo -n {helper} ensure {arguments}; echo "helper=$?"') + " 2>&1")
        assert "helper=2" in out, f"{arguments}: {out}"
    # A letter outside ASCII, called under a language setting in which letter ranges are wider
    for locale in ["en_US.UTF-8", "C.UTF-8"]:
        out = machine.succeed(asUser(f'LC_ALL={locale} sudo -n {helper} ensure alpha b1 wörker; echo "helper=$?"') + " 2>&1")
        assert "helper=2" in out and "invalid worker name" in out, f"{locale}: {out}"
    assert datasets() == before, datasets()
    # Not the user, and not without sudo
    machine.fail(f"sudo -u nobody {helper} mount-all")
    machine.fail(asUser(f"{helper} mount-all"))

with subtest("V13c: the helper while the caller tries to swap a folder on its way"):
    machine.succeed(asUser(f"(while :; do ln -sfn /var/lib/target {folders}/race 2>/dev/null; rm -f {folders}/race 2>/dev/null; done) > /dev/null 2>&1 & echo $! > ~/loop"))
    for name in ["n1", "n2", "n3"]:
        machine.succeed(asUser(f"sudo -n {helper} ensure race b {name}"))
        assert machine.succeed(f"findmnt -rn -o SOURCE --mountpoint {folders}/race/b/{name}").strip() == f"rpool/workers/race/b/{name}"
    machine.succeed(asUser("kill $(cat ~/loop)"))
    assert machine.succeed("ls /var/lib/target").split() == ["file"]
    assert machine.succeed(f"stat -c '%U' {folders}/race {folders}/race/b {folders}/race/b/n1").split() == ["root", "root", user]

with subtest("Round 6 item 4: every project and branch level above a worker belongs to root"):
    # Reproduction: a user-owned project level must be refused before a worker dataset is made or mounted below it
    machine.succeed(asUser("mkdir ~/owned-project && git -C ~/owned-project init -q -b main && git -C ~/owned-project commit -q --allow-empty -m base && git -C ~/owned-project branch b1"), f"mkdir {folders}/owned-project && chown {user}:users {folders}/owned-project")
    out = machine.fail(worker("b1", "w1", "true", project="owned-project") + " 2>&1")
    correction = f"sudo chown root:root {folders}/owned-project && sudo chmod 755 {folders}/owned-project"
    print("Round 6 item 4 project:", out)
    assert f"refusing: {folders}/owned-project" in out and correction in out, out
    machine.fail("zfs list rpool/workers/owned-project/b1/w1")

    # Control: the user's own old/ is a neighbour, not an ancestor, and remains his while a worker starts
    machine.succeed(f"chown root:root {folders}/owned-project; chmod 755 {folders}/owned-project; mkdir {folders}/owned-project/old; chown {user}:users {folders}/owned-project/old")
    machine.succeed(worker("b1", "w1", "true", project="owned-project"))
    assert machine.succeed(f"stat -c '%U' {folders}/owned-project/old").strip() == user

    # The same refusal covers a branch level and the scratch tree
    machine.succeed(asUser("git -C ~/owned-project branch b2"), f"mkdir {folders}/owned-project/b2; chown {user}:users {folders}/owned-project/b2")
    out = machine.fail(worker("b2", "w2", "true", project="owned-project") + " 2>&1")
    assert f"refusing: {folders}/owned-project/b2" in out and f"sudo chown root:root {folders}/owned-project/b2 && sudo chmod 755 {folders}/owned-project/b2" in out, out
    machine.succeed(f"mkdir {areas}/owned-area; chown {user}:users {areas}/owned-area")
    out = machine.fail(asUser(f"sudo -n {helper} ensure-area owned-area b1 w1") + " 2>&1")
    assert f"refusing: {areas}/owned-area" in out and f"sudo chown root:root {areas}/owned-area && sudo chmod 755 {areas}/owned-area" in out, out

with subtest("B3: project knowledge is user-owned, bounded, persistent and isolated"):
    project = "knowledge-a"
    otherProject = "knowledge-b"
    projectPath = f"{folders}/{project}"
    knowledgePath = f"{projectPath}/knowledge"
    commonPath = f"{knowledgePath}/common"
    branchPath = f"{knowledgePath}/b1"
    otherCommonPath = f"{folders}/{otherProject}/knowledge/common"
    commonDataset = f"rpool/workers/{project}/knowledge/common"
    branchDataset = f"rpool/workers/{project}/knowledge/b1"

    # The user's existing old/ folder is a neighbour of knowledge/ and must not change
    machine.succeed(
        f"install -d -o root -g root -m 755 {projectPath}",
        f"install -d -o {user} -g users -m 755 {projectPath}/old",
        f"printf kept-by-the-user > {projectPath}/old/marker",
        f"chown {user}:users {projectPath}/old/marker",
    )
    oldState = lambda: machine.succeed(
        f"stat -c '%U:%G:%a:%i' {projectPath}/old {projectPath}/old/marker; "
        f"sha256sum {projectPath}/old/marker; find {projectPath}/old -mindepth 1 -maxdepth 1 -printf '%f\\n' | sort"
    )
    oldBefore = oldState()

    # One branch request makes common and that branch, but no unrequested branch
    machine.succeed(asUser(f"sudo -n {helper} ensure-knowledge {project} b1"))
    machine.fail(f"test -e {knowledgePath}/b2")
    machine.succeed(asUser(f"sudo -n {helper} ensure-knowledge {project} b2"))
    listing = machine.succeed(f"zfs list -H -o name,quota,mounted,mountpoint -r rpool/workers/{project}")
    print("B3 knowledge datasets:", listing)
    for expected in [
        f"{commonDataset}\t64M\tyes\t{commonPath}",
        f"{branchDataset}\t64M\tyes\t{branchPath}",
        f"rpool/workers/{project}/knowledge/b2\t64M\tyes\t{knowledgePath}/b2",
    ]:
        assert expected in listing, expected
    owners = machine.succeed(
        f"stat -c '%U %a' {projectPath} {knowledgePath} {commonPath} {branchPath} {knowledgePath}/b2"
    ).split()
    assert owners == ["root", "755", "root", "755", user, "700", user, "700", user, "700"], owners
    machine.succeed(
        asUser(f"echo common-material > {commonPath}/paper && echo branch-material > {branchPath}/reference")
    )

    # The knowledge grouping name can never become a worker branch or scratch namespace
    commonState = lambda: machine.succeed(
        f"stat -c '%U:%G:%a:%i' {commonPath} {commonPath}/paper; sha256sum {commonPath}/paper; "
        f"find {commonPath} -mindepth 1 -maxdepth 1 -printf '%f\\n' | sort"
    )
    commonBefore = commonState()
    message = "'knowledge' cannot be a branch name: the project's folder of that name is in its place"
    for arguments in [
        f"ensure {project} knowledge common",
        f"ensure-area {project} knowledge common",
    ]:
        out = machine.fail(asUser(f"sudo -n {helper} {arguments}") + " 2>&1")
        assert message in out, out
    assert commonState() == commonBefore, (commonBefore, commonState())

    # A second project's fixed namespace is separate and cannot be selected by traversal
    machine.succeed(asUser(f"sudo -n {helper} ensure-knowledge {otherProject} b1"))
    machine.succeed(asUser(f"echo other-project > {otherCommonPath}/private"))
    out = machine.fail(asUser(f"sudo -n {helper} ensure-knowledge {project} ../{otherProject}") + " 2>&1")
    assert "invalid branch name" in out, out
    machine.succeed(
        f"test \"$(findmnt -rn -o SOURCE --mountpoint {commonPath})\" = {commonDataset}",
        f"test \"$(findmnt -rn -o SOURCE --mountpoint {otherCommonPath})\" = rpool/workers/{otherProject}/knowledge/common",
        f"test -z \"$(find -L {knowledgePath} -xdev -samefile {otherCommonPath} -print -quit)\"",
    )

    # The dynamic backup list and recursive snapshot rule include knowledge like other worker folders
    machine.succeed(f"cat > /tmp/knowledge-backup-list <<'END'\n{backupList}\nEND\nchmod +x /tmp/knowledge-backup-list")
    backedUp = machine.succeed("/tmp/knowledge-backup-list").split()
    for expected in [commonPath, branchPath, f"{knowledgePath}/b2", otherCommonPath]:
        assert expected in backedUp, (expected, backedUp)
    machine.succeed("rm -f /var/cache/private/sanoid/datasets.txt /var/cache/sanoid/datasets.txt; systemctl start --wait sanoid.service")
    snapshots = machine.succeed("zfs list -H -t snapshot -o name | grep autosnap || true")
    assert f"{commonDataset}@autosnap" in snapshots and f"{branchDataset}@autosnap" in snapshots, snapshots

    # An existing dataset is never silently remounted at a missing, moved or linked source path
    machine.succeed(f"zfs unmount {commonDataset}; rmdir {commonPath}")
    out = machine.fail(asUser(f"sudo -n {helper} ensure-knowledge {project} b1") + " 2>&1")
    assert commonPath in out and "missing or moved" in out, out
    machine.succeed(f"install -d -o root -g root -m 755 {commonPath}; zfs mount {commonDataset}")

    machine.succeed(f"zfs unmount {branchDataset}; mv {branchPath} {branchPath}.moved")
    out = machine.fail(asUser(f"sudo -n {helper} ensure-knowledge {project} b1") + " 2>&1")
    assert branchPath in out and "missing or moved" in out, out
    machine.succeed(f"mv {branchPath}.moved {branchPath}; zfs mount {branchDataset}")

    machine.succeed(f"zfs unmount {branchDataset}; mv {branchPath} {branchPath}.real; ln -s /var/lib/target {branchPath}")
    out = machine.fail(asUser(f"sudo -n {helper} ensure-knowledge {project} b1") + " 2>&1")
    assert branchPath in out and "reached through a link" in out, out
    machine.succeed(f"rm {branchPath}; mv {branchPath}.real {branchPath}; zfs mount {branchDataset}")

    machine.succeed(f"grep -qx common-material {commonPath}/paper; grep -qx branch-material {branchPath}/reference")
    assert oldState() == oldBefore, (oldBefore, oldState())

with subtest("V16a: the first start creates the worker's folder and scratch area, each a dataset with its limit"):
    out = machine.succeed(worker("b1", "w1", "pwd; env | grep -E '^(WORKER|UV)_' | sort; ls ~; ls ~/workers/alpha ~/workers/alpha/b1; ls ~/workers/alpha/b1/w1"))
    print("V16a inside:", out)
    lines = out.split()
    assert lines[0] == f"{folders}/alpha/b1/w1/repo", out
    assert f"WORKER_SCRATCH={areas}/alpha/b1/w1" in out and "WORKER_ROLE=implementer" in out and "WORKER_BRANCH=b1" in out, out
    assert f"UV_PROJECT_ENVIRONMENT={areas}/alpha/b1/w1/venv" in out and f"UV_CACHE_DIR={areas}/alpha/b1/w1/uv-cache" in out, out
    # Of the project the launcher was started in it sees the history only
    assert machine.succeed(worker("b1", "w1", "ls -A ~/alpha")).split() == [".git"], out
    # An ordinary session gets a scratch area of its own, and no folder
    machine.succeed(asUser("cd ~/alpha && worker-shell -c 'echo cached > $WORKER_SCRATCH/x'"))
    ordinary = machine.succeed("zfs list -H -o name,quota -r rpool | grep plain/session")
    print("V16a ordinary session:", ordinary)
    assert ordinary.startswith("rpool/scratch/workers/alpha-") and ordinary.strip().endswith("/plain/session\t96M") and "rpool/workers/alpha-" not in machine.succeed("zfs list -H -o name -r rpool"), ordinary
    listing = machine.succeed("zfs list -H -o name,quota,mounted,mountpoint -r rpool/workers/alpha rpool/scratch/workers/alpha")
    print("V16a datasets:", listing)
    for expected in [
        f"rpool/workers/alpha/b1/w1\t64M\tyes\t{folders}/alpha/b1/w1",
        f"rpool/scratch/workers/alpha/b1/w1\t96M\tyes\t{areas}/alpha/b1/w1",
        f"rpool/workers/alpha/instructions\t16M\tyes\t{folders}/alpha/instructions",
        f"rpool/workers/alpha/archive\tnone\tyes\t{folders}/alpha/archive",
    ]:
        assert expected in listing, expected
    owners = machine.succeed(f"stat -c '%U %a' {folders}/alpha {folders}/alpha/b1 {folders}/alpha/b1/w1 {areas}/alpha/b1 {areas}/alpha/b1/w1 {folders}/alpha/instructions").split()
    assert owners == ["root", "755", "root", "755", user, "700", "root", "755", user, "700", user, "700"], owners

with subtest("Views: an implementer's own places, its records read-only, its sessions its own; the manager reads every worker and writes none"):
    probe = (
        'echo r > repo-file; echo "repo=$?"; echo r > ../reports/report; echo "reports=$?"; echo r > ../records/forged; echo "records=$?";'
        ' echo s > ~/.pi/agent/sessions/mine; echo "sessions=$?"; echo d > $WORKER_SCRATCH/data; echo "scratch=$?";'
        ' cat ~/.ssh/id_test; echo "key=$?"; touch ~/alpha/.git/x; echo "history=$?"; ls ~/workers/alpha/instructions; echo "instructions=$?"'
    )
    out = machine.succeed(worker("b1", "w1", probe) + " 2>&1")
    print("implementer:", out)
    for expected in ["repo=0", "reports=0", "records=1", "sessions=0", "scratch=0", "key=1", "history=1", "instructions=2"]:
        assert expected in out, out
    machine.succeed(f"test -s {folders}/alpha/b1/w1/sessions/mine && test ! -e {home}/.pi/agent/sessions/mine && test ! -e {folders}/alpha/b1/w1/records/forged")
    # A second worker of the same branch sees neither the first one's folder, area nor sessions
    out = machine.succeed(worker("b1", "w2", f'ls ~/workers/alpha/b1; ls ~/.pi/agent/sessions | wc -l; cat {folders}/alpha/b1/w1/reports/report; echo "other-report=$?"; echo x > {areas}/alpha/b1/w1/intruder; echo "other-area=$?"') + " 2>&1")
    print("second worker:", out)
    assert out.split()[0:2] == ["w2", "0"] and "other-report=1" in out and "other-area=1" in out, out
    out = machine.succeed(
        manager(
            f'cat {folders}/alpha/b1/w1/reports/report {areas}/alpha/b1/w1/data; echo x > {folders}/alpha/b1/w1/reports/intruder; echo "folder-write=$?";'
            f' echo x > {areas}/alpha/b1/w1/intruder; echo "area-write=$?"; mkdir -p ~/workers/alpha/instructions/b1 && echo task > ~/workers/alpha/instructions/b1/w1.md; echo "instructions=$?";'
            ' echo m > ~/alpha/by-manager; echo "project=$?"; echo $WORKER_SCRATCH; pwd'
        )
        + " 2>&1"
    )
    print("manager:", out)
    # The manager works in a copy of its own; the project itself is read-only for it as for every worker
    for expected in ["r\nd\n", "folder-write=1", "area-write=1", "instructions=0", "project=1", f"{areas}/alpha/manager/manager", f"{folders}/alpha/manager/manager/repo"]:
        assert expected in out, out
    machine.succeed(f"test ! -e {folders}/alpha/b1/w1/reports/intruder && test ! -e {areas}/alpha/b1/w1/intruder && test ! -e {home}/alpha/by-manager")

with subtest("Round 6 item 2: a running manager reads a worker made later through its broker"):
    live = "echo manager-runs; until [ -e $WORKER_SCRATCH/read-go ]; do sleep 0.2; done; worker-read b1/read-late reports r; worker-read b1/read-late records runs.jsonl | grep -m1 '\"name\": \"read-late\"'; echo \"read=$?\""
    machine.succeed(f"(({manager(live)}); touch /tmp/read-late-ended) > /tmp/read-late 2>&1 &")
    machine.wait_until_succeeds("grep -q manager-runs /tmp/read-late", timeout=60 * pace)
    machine.succeed(worker("b1", "read-late", "echo made-later > ../reports/r; queue run -- true"), f"touch {areas}/alpha/manager/manager/read-go")
    machine.wait_until_succeeds("test -e /tmp/read-late-ended", timeout=60 * pace)
    out = machine.succeed("cat /tmp/read-late")
    print("live manager reader:", out)
    assert "made-later" in out and '"name": "read-late"' in out and out.rstrip().endswith("read=0"), out

with subtest("V16c: a folder and an area created after a manager and a deep reviewer started are neither visible nor writable for them"):
    # Each of the two says when its sandbox runs and waits at a gate; the new worker is made in between
    late = f'echo runs; until [ -e $WORKER_SCRATCH/late-go ]; do sleep 0.2; done; for p in {folders}/alpha/b1/late {areas}/alpha/b1/late; do if [ -e $p ]; then echo visible; else echo hidden; fi; if touch $p/x 2>/dev/null; then echo writable; else echo protected; fi; done'
    deep = asUser(f"cd ~/alpha && worker-shell --role deep-reviewer --branch b1 --name d1 -c {shlex.quote(late)}")
    machine.succeed("rm -f /tmp/late*", "(" + manager(late) + " > /tmp/late 2>&1; touch /tmp/late-ended) > /dev/null 2>&1 &", "(" + deep + " > /tmp/late-deep 2>&1; touch /tmp/late-deep-ended) > /dev/null 2>&1 &")
    machine.wait_until_succeeds("grep -q runs /tmp/late && grep -q runs /tmp/late-deep", timeout=60 * pace)
    machine.succeed(worker("b1", "late", "echo of-late > ../reports/r"), f"touch {areas}/alpha/manager/manager/late-go {areas}/alpha/b1/d1/late-go")
    machine.wait_until_succeeds("test -e /tmp/late-ended && test -e /tmp/late-deep-ended", timeout=60 * pace)
    out = machine.succeed("cat /tmp/late /tmp/late-deep")
    print("V16c:", out)
    assert out.split() == ["runs"] + ["hidden", "protected"] * 2 + ["runs"] + ["hidden", "protected"] * 2, out
    machine.succeed(f"test ! -e {folders}/alpha/b1/late/x && test ! -e {areas}/alpha/b1/late/x")
    # Control: a manager started afterwards reads it
    assert "of-late" in machine.succeed(manager(f"cat {folders}/alpha/b1/late/reports/r"))
    assert "of-late" in machine.succeed(asUser(f"cd ~/alpha && worker-shell --role deep-reviewer --branch b1 --name d1 -c 'cat {folders}/alpha/b1/late/reports/r'"))

with subtest("V16b: snapshot of one scratch area, a deletion, rollback"):
    machine.succeed(worker("b1", "w1", "mkdir -p $WORKER_SCRATCH/results && echo one > $WORKER_SCRATCH/results/one"))
    machine.succeed(asUser("cd ~/alpha && worker-shell --branch b1 --name w1 --snapshot before"))
    print("V16b snapshots:", machine.succeed(asUser("cd ~/alpha && worker-shell --branch b1 --name w1 --snapshots")))
    machine.succeed(worker("b1", "w2", "echo newer > $WORKER_SCRATCH/newer"))
    machine.succeed(worker("b1", "w1", "rm -rf $WORKER_SCRATCH/results $WORKER_SCRATCH/data"))
    machine.fail(f"test -e {areas}/alpha/b1/w1/results/one")
    machine.succeed(asUser("cd ~/alpha && worker-shell --branch b1 --name w1 --rollback before"))
    machine.succeed(f"grep -qx one {areas}/alpha/b1/w1/results/one && grep -qx d {areas}/alpha/b1/w1/data && grep -qx newer {areas}/alpha/b1/w2/newer")
    # A label cannot name another dataset
    machine.fail(asUser("cd ~/alpha && worker-shell --branch b1 --name w1 --snapshot x@y"))

with subtest("V19: every place a worker can write stops with an error, and nothing is killed"):
    # B1 of the deep review: the places are not a list written here. They are every mount that the sandbox itself lists and in which
    # a file can be made. One is left out by name: pi's login folder, which is the user's own and has no limit (accepted, D4)
    fill = r"""
findmnt -rn -o TARGET,FSTYPE | while read -r place kind; do
  [ -d "$place" ] || continue
  touch "$place/.probe" 2>/dev/null || continue
  rm -f "$place/.probe"
  if [ "$place" = "$HOME/.pi/agent/login" ]; then echo "$place skipped"; continue; fi
  head -c 200M /dev/urandom > "$place/big" 2>/dev/null; echo "$place full=$?"
  rm -f "$place/big"
  if [ "$kind" = zfs ]; then sync; sleep 6; fi
done
echo "alive=$?"
"""
    machine.succeed("cat > /tmp/fill.sh <<'END'\n" + fill + "\nEND", f"install -o {user} -m 755 /tmp/fill.sh {areas}/alpha/b1/w1/fill.sh")
    own = f"{folders}/alpha/b1/w1"
    places = ["/dev/shm", "/tmp", "/run", home, f"{home}/.pi/agent/sessions", f"{own}/repo", f"{own}/reports", f"{areas}/alpha/b1/w1"]
    expected = sorted([f"{place} full=1" for place in places] + [f"{home}/.pi/agent/login skipped", "alive=0"])
    for label, command in [("the agent", "bash $WORKER_SCRATCH/fill.sh"), ("a job", "queue run -- bash $WORKER_SCRATCH/fill.sh")]:
        out = machine.succeed(worker("b1", "w1", command) + " 2>&1")
        print(f"V19 {label}:", out)
        # In the job, the kept copy of what it prints goes to the scratch area, which the job itself has just filled: the copy
        # step says that it could not write the line, and the line still reaches the client
        said = [line for line in out.strip().splitlines() if not (label == "a job" and line.startswith("tee: ") and line.endswith("output.log: Disk quota exceeded"))]
        assert sorted(said) == expected, f"{label}: {out}"
    # /dev itself, the sandbox's top folder and the folder of the broker's socket are memory too: they take no file at all
    out = machine.succeed(worker("b1", "w1", 'for place in /dev / /run/worker /home; do touch $place/x 2>/dev/null; echo "$place=$?"; done; echo x > /dev/null; echo "null=$?"') + " 2>&1")
    assert out.split() == ["/dev=1", "/=1", "/run/worker=1", "/home=1", "null=0"], out
    # While the scratch area is full, the worker's folder still takes a file
    out = machine.succeed(worker("b1", "w1", 'head -c 200M /dev/urandom > $WORKER_SCRATCH/big 2>/dev/null; echo "scratch=$?"; echo ok > still-writable; echo "folder-while-scratch-full=$?"; rm -f $WORKER_SCRATCH/big') + " 2>&1")
    assert out.split() == ["scratch=1", "folder-while-scratch-full=0"], out
    out = machine.succeed(manager('head -c 200M /dev/urandom > ~/workers/alpha/instructions/big 2>/dev/null; echo "instructions=$?"; rm -f ~/workers/alpha/instructions/big; echo "alive=$?"') + " 2>&1")
    print("V19 manager:", out)
    assert "instructions=1" in out and "alive=0" in out, out
    # Control: the same writer succeeds where there is room, so the failures above are the limits
    machine.succeed(asUser("head -c 200M /dev/urandom > ~/scratch/control && rm ~/scratch/control"))
    # Another worker and the user are not affected
    machine.succeed(worker("b1", "w2", "echo ok > file && echo ok > $WORKER_SCRATCH/file"), asUser("echo ok > ~/own-file"))
    assert machine.succeed("journalctl -k --no-pager | grep -ci 'out of memory' || true").strip() == "0"

with subtest("B5: no job without a record"):
    records = f"{folders}/alpha/b1/w1/records/runs.jsonl"
    count = lambda: int(machine.succeed(f"(cat {records} 2>/dev/null || true) | wc -l"))
    before = count()
    # Z1 of the deep review: with the worker's folder full, the job is refused and nothing of it runs. Control: with room again,
    # the next job runs and has its two lines, one from its start and one from its end
    full = (
        'head -c 200M /dev/urandom > ../reports/big 2>/dev/null; sync; sleep 6; queue run -- bash -c "echo ran-without-a-record > \\$WORKER_SCRATCH/proof; echo job-output"; echo "exit=$?";'
        ' rm -f ../reports/big; sync; sleep 6; queue run -- echo after-the-space-was-freed; echo "exit=$?"'
    )
    out = machine.succeed(worker("b1", "w1", full) + " 2>&1")
    print("B5 (Z1 of the deep review):", out, "| the job's file:", machine.succeed(f"cat {areas}/alpha/b1/w1/proof 2>&1 || true").strip())
    assert "refused: the run could not be recorded (Disk quota exceeded), so nothing was run" in out and "job-output" not in out, out
    assert [line for line in out.splitlines() if line.startswith("exit=") or line.startswith("after")] == ["exit=2", "after-the-space-was-freed", "exit=0"], out
    machine.fail(f"test -e {areas}/alpha/b1/w1/proof")
    assert count() == before + 2, (before, count())
    # A job that fills the folder itself has its line of the start. Its status still reaches the client, with a word on the record
    during = 'queue run -- bash -c "head -c 200M /dev/urandom > ../reports/big 2>/dev/null; sync; sleep 6; exit 7"; echo "exit=$?"; rm -f ../reports/big'
    out = machine.succeed(worker("b1", "w1", during) + " 2>&1")
    print("B5, a job that fills the folder:", out)
    assert "queue: the end of this run could not be recorded (Disk quota exceeded); its start is in the records" in out and "exit=7" in out and "refused" not in out, out
    last = json.loads(machine.succeed(f"sync; sleep 6; tail -n 1 {records}"))
    assert last["state"] == "started" and "exit" not in last and count() == before + 3, last

with subtest("V20: the backup's list names every worker folder and no scratch area; sanoid snapshots a worker's folder"):
    machine.succeed(f"cat > /tmp/backup-list <<'END'\n{backupList}\nEND\nchmod +x /tmp/backup-list")
    listed = machine.succeed("/tmp/backup-list").split()
    print("V20 backup list:", listed)
    for expected in [folders, f"{folders}/alpha/b1/w1", f"{folders}/alpha/b1/late", f"{folders}/alpha/instructions", f"{folders}/alpha/archive", f"{folders}/alpha/manager/manager"]:
        assert expected in listed, expected
    assert not [path for path in listed if path.startswith(f"{home}/scratch")], listed
    # F2: a list that cannot be made is an error, not an empty list (here: no table of mounts to read)
    machine.fail("unshare -m sh -c 'mount -t tmpfs tmpfs /proc && /tmp/backup-list'")
    # sanoid keeps its list of datasets for 20 minutes; without this it would not see the ones created just now
    machine.succeed("rm -f /var/cache/private/sanoid/datasets.txt /var/cache/sanoid/datasets.txt; systemctl start --wait sanoid.service")
    snapshots = machine.succeed("zfs list -H -t snapshot -o name | grep autosnap || true")
    print("V20 snapshots:", snapshots)
    assert "rpool/workers/alpha/b1/w1@autosnap" in snapshots and "rpool/workers/alpha/instructions@autosnap" in snapshots, snapshots
    assert "rpool/scratch" not in snapshots, snapshots
    # A file a worker deleted is in the snapshot of its folder
    machine.succeed(worker("b1", "w1", "rm repo-file"))
    snapshot = machine.succeed("zfs list -H -t snapshot -o name rpool/workers/alpha/b1/w1 | grep hourly | head -n 1 | cut -d@ -f2").strip()
    machine.succeed(f"grep -qx r {folders}/alpha/b1/w1/.zfs/snapshot/{snapshot}/repo/repo-file")

with subtest("A snapshot of a worker's folder counts against its limit"):
    machine.succeed(worker("b1", "w1", "head -c 40M /dev/urandom > churn"), "sync; zfs snapshot rpool/workers/alpha/b1/w1@held")
    out = machine.succeed(worker("b1", "w1", 'rm churn; sync; sleep 6; head -c 40M /dev/urandom > churn2 2>/dev/null; echo "second=$?"; rm -f churn2'))
    print("snapshot and limit:", out, machine.succeed("zfs list -o name,used,usedbysnapshots,quota rpool/workers/alpha/b1/w1"))
    assert "second=1" in out, out
    # Control: without the snapshot the same file fits
    machine.succeed("zfs destroy rpool/workers/alpha/b1/w1@held; sync; sleep 6", worker("b1", "w1", "head -c 40M /dev/urandom > churn2 && rm churn2"))

with subtest("G-B: can a copy share its blocks with the original, within a dataset and between two workers' datasets"):
    first, same, second = f"{folders}/alpha/b1/w1/repo/blob", f"{folders}/alpha/b1/w1/repo/blob-copy", f"{folders}/alpha/b1/w2/repo/blob"
    machine.succeed(asUser(f"head -c 20M /dev/urandom > {first}"), "sync; sleep 6")
    saved = lambda: int(machine.succeed("sync; sleep 6; zpool get -H -p -o value bclonesaved rpool"))
    results = {"block cloning enabled": machine.succeed("cat /sys/module/zfs/parameters/zfs_bclone_enabled").strip(), "bytes saved before": saved()}
    for label, command in [
        ("within one dataset, cp --reflink=always", f"cp --reflink=always {first} {same}"),
        ("between two datasets, cp --reflink=always", f"cp --reflink=always {first} {second}"),
        ("between two datasets, cp --reflink=auto", f"cp --reflink=auto {first} {second}"),
    ]:
        status, out = machine.execute(asUser(command) + " 2>&1")
        results[label] = f"exit {status} {out.strip()[-40:]}; bytes saved now {saved()}"
    print("G-B:", results)
    # Whatever was shared: a change to either file never reaches the other
    original = machine.succeed(f"sha256sum < {first}")
    machine.succeed(asUser(f"echo more >> {second}; echo more >> {same}"))
    assert machine.succeed(f"sha256sum < {first}") == original
    copied = machine.succeed(f"sha256sum < {second}")
    machine.succeed(asUser(f"echo other >> {first}"))
    assert machine.succeed(f"sha256sum < {second}") == copied
    machine.succeed(asUser(f"rm -f {first} {same} {second}"))

with subtest("V17: removing a worker keeps its folder for a time, and only the system's timer destroys it"):
    target = "rpool/workers/alpha/b1/rm1"
    machine.succeed(worker("b1", "rm1", "echo work > work && git add work && git commit -q -m work && echo draft > draft && echo report > ../reports/final"))
    assert "has uncommitted changes" in machine.fail(asUser("workers remove alpha/b1/rm1") + " 2>&1")
    machine.succeed(worker("b1", "rm1", "rm draft; queue run -- true"))
    assert "has 1 commit(s)" in machine.fail(asUser("workers remove alpha/b1/rm1") + " 2>&1")
    # The manager merges the work and writes down the task it had given
    machine.succeed(manager(f"git fetch -q {folders}/alpha/b1/rm1/repo worker/b1/rm1:refs/workers/b1/rm1 && git checkout -q b1 && git merge -q --no-edit refs/workers/b1/rm1 && echo the-task > ~/workers/alpha/instructions/b1/rm1.md"))
    out = machine.succeed(asUser("workers remove alpha/b1/rm1"))
    print("V17 removed:", out, machine.succeed(f"zfs get -H -o property,value canmount,mounted,workers:retired {target}; (zfs list -H -o name rpool/scratch/workers/alpha/b1/rm1 2>&1 || true); ls {folders}/alpha/archive/b1-rm1-*; " + asUser("workers list") + " | grep rm1"))
    assert machine.succeed(f"zfs get -H -o value canmount,mounted {target}").split() == ["off", "no"] and machine.succeed(f"zfs get -H -o value workers:retired {target}").strip().isdigit()
    machine.fail("zfs list rpool/scratch/workers/alpha/b1/rm1")
    machine.succeed(f"grep -qx report {folders}/alpha/archive/b1-rm1-*/reports/final && grep -qx the-task {folders}/alpha/archive/b1-rm1-*/task.md && test -s {folders}/alpha/archive/b1-rm1-*/records/runs.jsonl")
    assert "removed, kept to" in machine.succeed(asUser("workers list") + " | grep rm1")
    # The approval is set aside with the worker, and comes back with it
    records = f"{home}/.local/state/workers/alpha"
    machine.succeed(f"test ! -e {records}/approvals/b1/rm1 && test -e {records}/approvals-removed/b1/rm1 && test -e {records}/roles-removed/b1/rm1")
    # The name stays taken, so that a new worker does not inherit the old one's snapshots
    out = machine.fail(worker("b1", "rm1", "true") + " 2>&1")
    assert "was removed and its folder is kept until" in out, out
    # Restored: the folder with its files, and a scratch area made again at the next start
    machine.succeed(asUser("workers restore alpha/b1/rm1"), f"test -e {records}/approvals/b1/rm1 && test ! -e {records}/approvals-removed/b1/rm1")
    machine.succeed(worker("b1", "rm1", "grep -qx report ../reports/final && grep -qx work work && echo again > $WORKER_SCRATCH/again", locked=True))
    # No caller through sudo can destroy a folder: the timer's action is refused, and there is no other
    for arguments in ["expire", "destroy alpha b1 rm1", "drop alpha b1 rm1"]:
        out = machine.fail(asUser(f"sudo -n {helper} {arguments}") + " 2>&1")
        print(f"V17 through sudo, {arguments}:", out.strip())
    assert machine.succeed(f"zfs list -H -o name {target}").strip() == target
    # The timer leaves a folder that was removed just now, and destroys one whose mark is older than the holding time
    machine.succeed(asUser("workers remove alpha/b1/rm1"), f"zfs snapshot {target}@kept", "systemctl start worker-datasets-expire.service")
    assert machine.succeed(f"zfs list -H -o name {target}").strip() == target
    machine.succeed(f"zfs set workers:retired=$(($(date +%s) - 15 * 86400)) {target}", "systemctl start worker-datasets-expire.service")
    machine.fail(f"zfs list {target}")
    print("V17 timer:", machine.succeed("journalctl -u worker-datasets-expire.service --no-pager | grep destroying"))
    # A leftover of earlier rounds: with the folder, the tools' records of the removed worker go, at the tool's next call. Control:
    # they were there until then. A later worker of that name finds no approval and no role
    machine.succeed(f"test -e {records}/roles-removed/b1/rm1 && test -e {records}/approvals-removed/b1/rm1 && test -e {records}/starts/b1/rm1")
    assert "rm1" not in machine.succeed(asUser("workers list"))
    left = machine.succeed(f"find {records} -name rm1 -not -path '*/mirror.git/*'").split()
    assert left == [], left
    # Control: the records of a worker that was removed and whose folder is kept are not touched by that
    machine.succeed(worker("b1", "rmk", "true"), asUser("workers remove alpha/b1/rmk && workers list > /dev/null"), f"test -e {records}/roles-removed/b1/rmk && test -e {records}/approvals-removed/b1/rmk")
    machine.succeed(asUser("workers restore alpha/b1/rmk"))
    # Finding 3 (R3 of the review): a removal while a terminal of the user's stands in the worker's scratch area changes nothing
    machine.succeed(worker("b1", "rm3", "echo report > ../reports/final"))
    state = lambda name="rm3": machine.succeed(
        f"zfs get -H -o value canmount,mounted,workers:retired rpool/workers/alpha/b1/{name} | tr '\\n' ' '; zfs get -H -o value mounted rpool/scratch/workers/alpha/b1/{name};"
        f" ls {home}/.local/state/workers/alpha/roles/b1 | grep -c {name}; (ls -d {folders}/alpha/archive/b1-{name}-* 2>/dev/null || true) | wc -l; " + asUser("workers list") + f" | grep {name} | awk '{{ print $5 }}'"
    ).split()
    before = state()
    machine.succeed(f"(cd {areas}/alpha/b1/rm3 && exec sleep 600) > /dev/null 2>&1 &")
    out = machine.fail(asUser("workers remove alpha/b1/rm3") + " 2>&1")
    print("R3 while the area is in use:", out.strip(), "| state:", state())
    assert "is in use" in out and "was not removed and is as it was" in out and state() == before == ["noauto", "yes", "-", "yes", "1", "0", "stopped"], (before, state())
    # The worker still starts, and a second attempt after the terminal is closed completes the removal, with one archive
    machine.succeed(worker("b1", "rm3", "grep -qx report ../reports/final"), "pkill -x -f 'sleep 600'; while pgrep -x -f 'sleep 600' > /dev/null; do sleep 0.1; done", asUser("workers remove alpha/b1/rm3"))
    assert machine.succeed(f"ls -d {folders}/alpha/archive/b1-rm3-* | wc -l").strip() == "1" and "removed" in machine.succeed(asUser("workers list") + " | grep rm3")

    # R2: a manager that has the worker's places in its mount view causes a named refusal before any removal state changes
    machine.succeed(worker("b1", "rm6", "echo report > ../reports/final"))
    before = state("rm6")
    machine.succeed(f"({manager('touch $WORKER_SCRATCH/rm6-manager-runs; while [ ! -e $WORKER_SCRATCH/rm6-manager-end ]; do sleep 0.2; done')}) > /tmp/rm6-manager 2>&1 &")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/manager/rm6-manager-runs", timeout=30 * pace)
    out = machine.fail(asUser("workers remove alpha/b1/rm6") + " 2>&1")
    print("R2 manager holds worker places:", out.strip(), "| state:", state("rm6"))
    assert "manager/manager" in out and "holds alpha/b1/rm6" in out and "was not removed and is as it was" in out and state("rm6") == before, (out, before, state("rm6"))
    machine.succeed(f"touch {areas}/alpha/manager/manager/rm6-manager-end")
    machine.wait_until_succeeds(asUser("! systemctl --user is-active --quiet worker:alpha:manager:manager.scope"), timeout=30 * pace)
    out = machine.succeed(asUser("workers remove alpha/b1/rm6"))
    assert "removed alpha/b1/rm6" in out and machine.succeed(f"ls -d {folders}/alpha/archive/b1-rm6-* | wc -l").strip() == "1", out

    # R2: the project lifecycle lock serializes a start against removal before that start can acquire worker places
    machine.succeed(f"rm -f /tmp/remove-lock-held /tmp/remove-lock-release {areas}/alpha/manager/manager/remove-race-mounted")
    machine.succeed(asUser("flock -x /run/user/1000/workers/worker:alpha.lifecycle.lock -c 'touch /tmp/remove-lock-held; while [ ! -e /tmp/remove-lock-release ]; do sleep 0.2; done'") + " > /tmp/remove-lock 2>&1 &")
    machine.wait_until_succeeds("test -e /tmp/remove-lock-held", timeout=10 * pace)
    machine.succeed(f"({manager('touch $WORKER_SCRATCH/remove-race-mounted')}) > /tmp/remove-race-manager 2>&1 &")
    machine.sleep(2)
    machine.fail(f"test -e {areas}/alpha/manager/manager/remove-race-mounted")
    machine.succeed("touch /tmp/remove-lock-release")
    machine.wait_until_succeeds(f"test -e {areas}/alpha/manager/manager/remove-race-mounted", timeout=30 * pace)

    # A removal interrupted after the folder was marked (here: the helper called without the tool): the tool's next call completes it
    machine.succeed(worker("b1", "rm4", "true"), asUser(f"sudo -n {helper} retire alpha b1 rm4"))
    assert machine.succeed(asUser("workers list") + " | grep rm4 | awk '{ print $5 }'").strip() == "stopped"
    out = machine.succeed(asUser("workers remove alpha/b1/rm4"))
    assert "an earlier removal was completed" in out and "removed" in machine.succeed(asUser("workers list") + " | grep rm4"), out
    machine.succeed(asUser("workers restore alpha/b1/rm4"), worker("b1", "rm4", "true"))
    # The other place that can be in use: a terminal in the worker's folder. The scratch area was unmounted before the folder
    # could not be; it is mounted again, with its files, and nothing was changed
    machine.succeed(worker("b1", "rm5", "echo kept > $WORKER_SCRATCH/kept; echo report > ../reports/final"))
    before = state("rm5")
    machine.succeed(f"(cd {folders}/alpha/b1/rm5/reports && exec sleep 601) > /dev/null 2>&1 &")
    out = machine.fail(asUser("workers remove alpha/b1/rm5") + " 2>&1")
    print("the folder in use:", out.strip(), "| state:", state("rm5"))
    assert "the folder of alpha/b1/rm5 is in use" in out and "was not removed and is as it was" in out and state("rm5") == before == ["noauto", "yes", "-", "yes", "1", "0", "stopped"], (before, state("rm5"))
    machine.succeed(f"grep -qx kept {areas}/alpha/b1/rm5/kept", "pkill -x -f 'sleep 601'; while pgrep -x -f 'sleep 601' > /dev/null; do sleep 0.1; done")
    # R2: if destruction of the scratch dataset fails, the helper rolls the worker back completely and the archive is removed
    area = "rpool/scratch/workers/alpha/b1/rm5"
    machine.succeed(f"zfs snapshot {area}@held && zfs hold keep {area}@held")
    out = machine.fail(asUser("workers remove alpha/b1/rm5") + " 2>&1")
    print("scratch destruction fails atomically:", out.strip(), "| state:", state("rm5"))
    assert "was not removed and is as it was" in out and state("rm5") == before, (out, before, state("rm5"))
    assert machine.succeed(f"(ls -d {folders}/alpha/archive/b1-rm5-* 2>/dev/null || true) | wc -l").strip() == "0"

    # A worker left half removed by an earlier version is still completed on the next call; a real held snapshot blocks one retry
    folder = "rpool/workers/alpha/b1/rm5"
    retired = machine.succeed("date +%s").strip()
    machine.succeed(f"zfs unmount {area}; zfs unmount {folder}; zfs set canmount=off workers:retired={retired} {folder}")
    out = machine.fail(asUser("workers remove alpha/b1/rm5") + " 2>&1")
    assert "earlier removal" in out and state("rm5")[0:3] == ["off", "no", retired], (out, state("rm5"))
    machine.succeed(f"zfs release keep {area}@held")
    out = machine.succeed(asUser("workers remove alpha/b1/rm5"))
    assert "an earlier removal was completed" in out and machine.succeed(f"(ls -d {folders}/alpha/archive/b1-rm5-* 2>/dev/null || true) | wc -l").strip() == "0", out
    machine.fail(f"zfs list {area}")
    assert "removed" in machine.succeed(asUser("workers list") + " | grep rm5")
    # A copy replaced by a link to another folder, from outside: the removal does not reach through it
    machine.succeed(worker("b1", "rm2", "true"), asUser(f"mv {folders}/alpha/b1/rm2/repo {folders}/alpha/b1/rm2/repo.real && ln -s {home}/alpha {folders}/alpha/b1/rm2/repo"))
    machine.execute(asUser("workers remove alpha/b1/rm2"))
    machine.succeed(asUser("git -C ~/alpha rev-parse HEAD && test -d ~/alpha/.git"))
    # H4: an ordinary session's scratch area is listed and can be removed
    session = machine.succeed(asUser("workers list") + " | awk '$4 == \"session\" { print $1 }'").strip()
    machine.succeed(asUser(f"workers remove-session {session}"))
    machine.fail(f"zfs list rpool/scratch/workers/{session}/plain/session")
    assert session not in machine.succeed(asUser("workers list"))

with subtest("W16: workers remove --merged removes merged implementers and their finished reviewers, and ignores the user's old folder"):
    held = lambda name: f"git fetch -q {folders}/alpha/b1/{name}/repo worker/b1/{name}:refs/workers/b1/{name} && git checkout -q b1 && git merge -q --no-edit refs/workers/b1/{name}"
    machine.succeed(asUser("git -C ~/alpha branch old"), f"mkdir {folders}/alpha/old && echo kept-by-the-user > {folders}/alpha/old/marker")
    oldState = lambda: machine.succeed(f"stat -c '%U:%G:%a:%i' {folders}/alpha/old {folders}/alpha/old/marker; sha256sum {folders}/alpha/old/marker; find {folders}/alpha/old -mindepth 1 -maxdepth 1 -printf '%f\\n' | sort")
    oldBefore = oldState()
    assert not [line for line in machine.succeed(asUser("workers list")).splitlines() if line.split()[1:2] == ["old"]]
    assert not [entry for entry in json.loads(machine.succeed(asUser("workers status --json")))["workers"] if entry["branch"] == "old"]
    row = lambda name: [line.split() for line in machine.succeed(asUser("workers list")).splitlines() if line.split()[:3] == ["alpha", "b1", name]][0]
    # m1 and m3: their work is in the manager's copy. m2: a commit that nobody else holds. Each reported a clean copy at its last run
    for name in ["m1", "m2", "m3"]:
        machine.succeed(worker("b1", name, f"echo {name} > {name} && git add {name} && git commit -q -m {name} && queue run -- true && echo report > ../reports/final"))
    tasks = "mkdir -p ~/workers/alpha/instructions/b1"
    for name in ["r-gone", "r-stay", "r-both"]:
        tasks += f" && printf 'branch: b1\\nname: {name}\\nrole: reviewer\\n\\nReview.\\n' > ~/workers/alpha/instructions/b1/{name}.md"
    machine.succeed(manager(tasks))
    review = lambda name, of: asUser(f"cd ~/alpha && worker-shell --role reviewer --branch b1 --name {name} --of {of} -c true")
    machine.succeed(review("r-gone", "m1"), review("r-stay", "m2"), review("r-both", "m1"), review("r-both", "m2"))
    machine.succeed(manager(held("m1") + " && " + held("m3")))
    # m3 has a file since then that is not committed, and has run nothing: the list still calls it removable, on its last word
    machine.succeed(worker("b1", "m3", "echo draft > draft"))
    rows = {name: row(name) for name in ["m1", "m2", "m3"]}
    print("W16, the list before:", rows)
    assert [rows[name][4] for name in ["m1", "m2", "m3"]] == ["removable", "stopped", "removable"] and [rows[name][-1] for name in ["m1", "m2", "m3"]] == ["0", "1", "0"], rows
    # The reminder: its sentence, with the space that the removable ones hold; the service that says it; the timer that starts it weekly
    document = json.loads(machine.succeed(asUser("workers status --json")))
    removable = [entry for entry in document["workers"] if entry.get("removable", {}).get("value")]
    holding = sum(entry[key]["used"] for entry in removable for key in ("folder", "scratch")) / 2**30
    sentence = machine.succeed(asUser("workers status --reminder")).strip()
    print("W16, the reminder:", sentence)
    assert {entry["name"] for entry in removable} == {"m1", "m3"} and sentence.startswith(f"{len(removable)} worker(s) can be removed") and f"They hold {holding:.1f} GiB." in sentence and "workers remove --merged alpha" in sentence, sentence
    machine.succeed(asUser("systemctl --user start workers-reminder.service"))
    said = machine.succeed("journalctl --no-pager _SYSTEMD_USER_UNIT=workers-reminder.service")
    assert f"{len(removable)} worker(s) can be removed" in said, said
    assert "workers-reminder.timer" in machine.succeed(asUser("systemctl --user list-timers --all --no-legend"))
    # The removal: m1 goes, by the removal that can be undone. m3 fails the question that is asked again now, and m2 was never
    # a candidate: both are left, each named with the reason
    before = machine.succeed("zfs get -H -o value mounted rpool/workers/alpha/b1/m2 rpool/workers/alpha/b1/m3").split()
    out = machine.succeed(asUser("workers remove --merged alpha") + " 2>&1")
    print("W16:", out)
    lines = out.strip().splitlines()
    assert [line for line in lines if line.startswith("removed alpha/b1/m1: records, reports and task are in ")], out
    assert "left alpha/b1/m2: 1 commit(s) that neither the project nor a manager's copy holds" in lines, out
    assert [line for line in lines if line.startswith("left alpha/b1/m3: refusing: the copy of alpha/b1/m3 has uncommitted changes")], out
    assert [line for line in lines if line.startswith("removed alpha/b1/r-gone: records, reports and task are in ")], out
    assert "left alpha/b1/r-stay: reviewed implementer(s) still present: m2" in lines, out
    assert "left alpha/b1/r-both: reviewed implementer(s) still present: m2" in lines, out
    removedLines = [line for line in lines if line.startswith("removed ")]
    assert len(removedLines) == 2 and any("alpha/b1/m1" in line for line in removedLines) and any("alpha/b1/r-gone" in line for line in removedLines), out
    assert lines[-1].startswith("2 worker(s) of alpha removed"), out
    # m1 and its finished reviewer: archived, their folders kept and marked; the others as they were
    assert machine.succeed("zfs get -H -o value canmount,mounted rpool/workers/alpha/b1/m1").split() == ["off", "no"] and machine.succeed("zfs get -H -o value workers:retired rpool/workers/alpha/b1/m1").strip().isdigit()
    machine.succeed(f"grep -qx report {folders}/alpha/archive/b1-m1-*/reports/final")
    assert machine.succeed("zfs get -H -o value mounted rpool/workers/alpha/b1/m2 rpool/workers/alpha/b1/m3").split() == before == ["yes", "yes"]
    assert machine.succeed("zfs get -H -o value canmount,mounted rpool/workers/alpha/b1/r-gone").split() == ["off", "no"]
    assert machine.succeed("zfs get -H -o value mounted rpool/workers/alpha/b1/r-stay rpool/workers/alpha/b1/r-both").split() == ["yes", "yes"]
    assert "removed, kept to" in " ".join(row("m1")) and row("m2")[4] == "stopped", (row("m1"), row("m2"))
    assert oldState() == oldBefore, (oldBefore, oldState())
    oldStatus, oldStart = machine.execute(worker("old", "hand", "true", locked=True) + " 2>&1")
    helperStatus, helperOld = machine.execute(asUser(f"sudo -n {helper} ensure alpha old helper-probe") + " 2>&1")
    print("the user's old folder, start on branch old:", oldStatus, oldStart.strip(), "| helper:", helperStatus, helperOld.strip())
    oldAfter = oldState()
    # It can be undone
    machine.succeed(asUser("workers restore alpha/b1/m1"), worker("b1", "m1", "grep -qx m1 m1 && grep -qx report ../reports/final", locked=True))
    # With nothing removable left, the reminder says nothing (m1 has no scratch area's report since its restore: it ran nothing)
    machine.succeed(worker("b1", "m3", "queue run -- true"), worker("b1", "m1", "echo draft > draft; queue run -- true"))
    assert [entry["name"] for entry in json.loads(machine.succeed(asUser("workers status --json")))["workers"] if entry.get("removable", {}).get("value")] == []
    assert machine.succeed(asUser("workers status --reminder")).strip() == ""
    # Refused for what is not a project with workers
    assert "has no workers" in machine.fail(asUser("workers remove --merged nothing-here") + " 2>&1")

with subtest("A hand-made old folder is untouched, and old cannot be a worker branch"):
    assert oldStatus != 0 and "cannot be a branch name" in oldStart, oldStart
    assert helperStatus != 0 and "cannot be a branch name" in helperOld, helperOld
    assert oldAfter == oldBefore, (oldBefore, oldAfter)

with subtest("W18: workers approve --empty-scratch returns the scratch area to what it was when the worker was made"):
    area = "rpool/scratch/workers/alpha/b1"
    approvals = f"{home}/.local/state/workers/alpha/approvals/b1"
    holds = lambda name: machine.succeed(f"ls -A {areas}/alpha/b1/{name}").split()
    snapshots = lambda name: machine.succeed(f"zfs list -H -t snapshot -o name {area}/{name}").split()
    planned(machine, "es1")
    planned(machine, "es2")
    # A new scratch area has its snapshot from the moment it was made; what the worker wrote while planning is in the area
    assert snapshots("es1") == [f"{area}/es1@created"] and holds("es1") == ["draft", "runs"], (snapshots("es1"), holds("es1"))
    # A later snapshot of the user's own
    machine.succeed(asUser("cd ~/alpha && worker-shell --branch b1 --name es1 --snapshot mine"))
    # Control: an approval without the option leaves the area as it is
    assert "approved (no tests" in machine.succeed(approve("es2"))
    assert holds("es2") == ["draft", "runs"]
    # Refused while the worker runs: nothing is emptied and nothing approved
    # (the worker waits at a gate, in its reports: its scratch area is what this subtest looks at)
    machine.succeed(f"({worker('b1', 'es1', 'until [ -e ../reports/es1-go ]; do sleep 0.2; done', locked=True)}) > /dev/null 2>&1 &")
    machine.wait_until_succeeds(asUser("systemctl --user is-active --quiet worker:alpha:b1:es1.scope"), timeout=20 * pace)
    out = machine.fail(approve("es1", "--empty-scratch"))
    assert "alpha/b1/es1 is running: end its session first. Nothing was approved" in out, out
    machine.succeed(f"test ! -e {approvals}/es1", f"touch {folders}/alpha/b1/es1/reports/es1-go")
    machine.wait_until_succeeds(asUser("! systemctl --user is-active --quiet worker:alpha:b1:es1.scope"), timeout=30 * pace)
    machine.succeed(f"rm {folders}/alpha/b1/es1/reports/es1-go")
    assert holds("es1") == ["draft", "runs"]
    # With the option: the area is empty, mounted and the worker's; the approval is recorded; later snapshots are gone with it
    out = machine.succeed(approve("es1", "--empty-scratch"))
    print("W18:", out[-400:])
    assert "the scratch area of alpha/b1/es1 is as it was when the worker was made: empty" in out and "approved (no tests" in out, out
    assert holds("es1") == [] and snapshots("es1") == [f"{area}/es1@created"] and machine.succeed(f"zfs get -H -o value mounted {area}/es1").strip() == "yes"
    machine.succeed(f"test -e {approvals}/es1")
    assert machine.succeed(worker("b1", "es1", "echo new > $WORKER_SCRATCH/new && echo change >> notes && echo writable", locked=True)).strip() == "writable"
    # Asked for a worker whose snapshot is gone, it says so and approves nothing
    planned(machine, "es3")
    machine.succeed(f"zfs destroy {area}/es3@created")
    out = machine.fail(approve("es3", "--empty-scratch"))
    assert "could not be emptied" in out and "Nothing was approved" in out, out
    machine.succeed(f"test ! -e {approvals}/es3")

with subtest("The status on a machine with the datasets: how full a worker's folder and scratch area are, against their limits"):
    document = json.loads(machine.succeed(asUser("workers status --json")))
    w1 = [entry for entry in document["workers"] if (entry["project"], entry["branch"], entry["name"]) == ("alpha", "b1", "w1")][0]
    print("status, the disk:", document["machine"]["disk"], "| the worker w1:", w1["folder"], w1["scratch"])
    used = lambda dataset: int(machine.succeed(f"zfs get -H -p -o value used {dataset}"))
    # The limits exactly; what is used within a mebibyte of what ZFS says a moment later
    assert w1["folder"]["limit"] == 64 << 20 and w1["scratch"]["limit"] == 96 << 20, (w1["folder"], w1["scratch"])
    assert abs(w1["folder"]["used"] - used("rpool/workers/alpha/b1/w1")) <= 1 << 20 and abs(w1["scratch"]["used"] - used("rpool/scratch/workers/alpha/b1/w1")) <= 1 << 20
    assert abs(document["machine"]["disk"]["workers"]["used"] - used("rpool/workers")) <= 4 << 20 and document["machine"]["disk"]["scratch"]["used"] > 0, document["machine"]["disk"]
    # The dashboard's reader accepts the document of this machine too (the start script of this check passes its program on)
    watch = watchProgram
    machine.succeed("cat > /tmp/status.json <<'END-OF-THE-DOCUMENT'\n" + json.dumps(document) + "\nEND-OF-THE-DOCUMENT")
    assert machine.execute(f"{watch} --validate --file /tmp/status.json 2>&1") == (0, ""), machine.execute(f"{watch} --validate --file /tmp/status.json 2>&1")

with subtest("After a reboot the workers' datasets are mounted again, after their parents"):
    machine.shutdown()
    machine.start()
    boot()
    print(machine.succeed("systemctl status worker-datasets-mount.service --no-pager | head -n 4; findmnt -rn -t zfs -o TARGET | sort"))
    machine.succeed("systemctl is-active worker-datasets-mount.service")
    machine.succeed(
        f"grep -qx r {folders}/alpha/b1/w1/reports/report && grep -qx one {areas}/alpha/b1/w1/results/one && grep -qx task {folders}/alpha/instructions/b1/w1.md",
        f"grep -qx common-material {folders}/knowledge-a/knowledge/common/paper && grep -qx branch-material {folders}/knowledge-a/knowledge/b1/reference",
    )
    machine.succeed(worker("b1", "w1", "echo after-reboot > $WORKER_SCRATCH/again"))
    print(machine.succeed("zfs list -o name,used,quota,mounted -r rpool | head -n 40"))
