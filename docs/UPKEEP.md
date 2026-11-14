# Upkeep: checks, guarded commits and updates

One command, `config`, keeps this repository and `nixos-secrets`. It is run by the user, outside any pi sandbox. On the workstations it is installed; elsewhere: `nix run "path:$PWD#config" -- <command>`, or the admin shell (`nix develop`).

| Command | What it does |
| --- | --- |
| `config check` | Runs the checks on the staged content and records that exactly this content passed |
| `config commit "<message>"` | Stages everything, runs the checks, asks for a typed `yes` when protected files change, commits and pushes |
| `config update <what>` | Fetches new versions, shows what changed and runs the checks; it does not commit |
| `config build <host>` | Builds a host's system from the last commit; `config build <host> vm` builds its virtual machine. The result is the link `result` |
| `config switch` | On a NixOS machine: builds this machine's system from the last commit and switches to it; it asks for sudo's password |
| `config install <arguments>` | Runs the install tool of [INSTALL.md](INSTALL.md) from the last commit |

The checks and the three build commands never read the folder. They take the content from git, the staged content for a check and the last commit for a build, and write it into a new folder, byte for byte. A file that git ignores, or that is not committed, takes no part.

In `nixos-config` the checks are `nix flake check`. In `nixos-secrets` the check is that every value in every file below `secrets/`, at any depth, is encrypted. sops calls a file encrypted as soon as it carries sops' own block, also when a plain value was typed in by hand, so the check looks at every value; it prints names, never a value. A file there that is not YAML or JSON is refused, because the check cannot read it.

## What an agent cannot change

Three things hold on NixOS whatever an agent is told or decides:

1. **`.git` is read-only in every pi session** (`docs/MIMIR-VM.md`, section pi): an agent cannot stage, commit or push.
2. **Protected files are read-only in a pi session** unless the user starts it with `pi --unlock`. The list is in `config-tool/protected.nix`:

   | Repository | Protected | Why |
   | --- | --- | --- |
   | `nixos-config` | `modules/dev/pi.nix`, `AGENTS.md` | What an agent's sandbox is, and its instructions |
   | | `config-tool/` | This list and the guard |
   | | `modules/flake/` | How the flake is put together: the checks, the package set, the hosts, the admin shell, the `config` command |
   | | `dev-env/` | The development environments, their checks and the checks' scripts |
   | | `modules/security/`, `modules/services/backup.nix`, `modules/storage/`, `modules/install/`, `install/`, `modules/boot/` | A wrong change loses data or access |
   | | `modules/profiles/`, `modules/hosts/`, `modules/users/` | The accounts, sudo, the firewall, the Nix settings, and what each host is made of |
   | | `modules/dev/git/`, `modules/dev/ssh.nix`, `modules/services/search.nix` | Where git and ssh run programs; modules that carry a check of their own |
   | | `flake.nix`, `flake.lock` | Which versions of everything are used |
   | | `.gitignore` | Which files git leaves out of every status and commit |
   | | `modules/dev/direnv.nix`, `.envrc` | What direnv evaluates in your own shell |
   | `nixos-secrets` | `AGENTS.md`, `.sops.yaml`, `secrets/` | Who may decrypt, and the encrypted values |
   | | `pi/`, `ssh/`, `desktop/`, `.gitignore` | Plain files that become part of the system: the instructions of every agent, the list of hosts that ssh reads, the desktops' names |

   Not protected, so that everyday changes need no `--unlock`: the applications (`modules/apps/`), the desktop (`modules/desktop/`), the hardware modules, the editor, Wi-Fi, VPN, Docker and libvirt, and the documents.

   As mounts they can neither be changed nor renamed, removed or replaced. `pi --unlock` says which files it opens, for that one session. A repository that holds an `AGENTS.override.md`, which pi would read instead of `AGENTS.md`, is refused. The protection goes with the repository's place: it is the same wherever below the repository pi starts and when the repository is shared with `--allow`, where `--unlock` opens it too.
3. **A commit passes two gates, and so does a push**, in `config commit` and, for plain `git commit` and `git push`, in two hooks that the user's own git settings name for the two repositories (an agent only reads those settings). The push needs its own hook because git makes commits without asking the first one: a merge, a fast-forward, a cherry-pick, a rebase. At a push, a commit that went through the guard when it was made passes without a word. For the others the push names them, shows what the branch changes on the remote, all commits together, and asks for the typed `yes`; and the content the branch will have must have passed the checks (`config check`). The two gates:
   - the checks passed on exactly the staged content, exported from git: a change after the check, or a failed check, stops the commit. A file below `modules/` that git ignores stops the check and the commit, and is named;
   - every change of a protected file and every change below `modules/` is listed and needs one typed `yes` per commit; in `nixos-secrets`, so does every new file, since that repository is pushed and copied to the Nix store of every machine that builds. Before the question git itself shows a summary of all of it, then the protected files and the added or removed modules in full, in its own viewer (`q` closes it); look at the changed modules with `git diff --cached`. Without a terminal to ask on, the commit is refused.
4. **The settings that matter are only set by protected files, and have the values that were decided.** Nix merges every module, so an ordinary module could also set the firewall or the backup's list. Two kinds of assertion in `modules/flake/checks.nix` stop that:
   - by place: the module system reports which file defines an option. For the backup, the firewall, the accounts, sudo, the Nix settings and package set, the secrets' key, the disk and boot settings, what every shell of yours runs, your git and ssh settings, and the flake's own checks, programs and shells, every defining file of this repository must be on the protected list;
   - by value: no port is open and only the loopback interface is trusted, `root` is the only trusted user of the Nix daemon, and the backup leaves out exactly what [BACKUP.md](BACKUP.md) lists.

Limits, stated plainly:
- **On a machine where pi runs without the sandbox** (Ubuntu before the move) none of this is enforced against an agent; `config commit` still applies the two gates to the user's own commits.
- **Every file below `modules/` is loaded**, and no list of guarded settings is complete: an ordinary module can still add what nobody listed, for example a service that runs as root. A module can also give a made-up file name for what it defines, which the assertion by place then believes; the assertions by value do not depend on it. That is why the guard asks about every commit that changes a module; the user's review of the commit is the last line.
- `git commit --no-verify` and `git push --no-verify` skip the hooks. Only the user can commit and push, so that is his decision.
- At a push of commits that did not go through the guard, the question shows their combined change. What one of them added and a later one removed again is in the history that is pushed, and not in what is shown.
- **Building the folder directly** (`nixos-rebuild --flake .`, `nix build "path:$PWD#…"`) reads whatever lies in the folder, also files that git ignores and changes that nobody has confirmed. Use `config build` and `config switch`, which take the last commit and refuse unless the checks passed on it and the folder holds nothing else.
- The record of a passed check is a file in `~/.local/state/config-checks/`, a hidden folder that no sandbox sees.

## After a change: build and switch

1. Review the change (`git diff`), then `config commit "<message>"`: the checks run, protected changes ask for `yes`, the commit is pushed.
2. On the NixOS machine itself: `config switch`. It builds the system of that commit and switches to it.
3. From another machine, or to look before switching: `config build <host>` builds the system without touching the running one; `config build mimir-vm vm` builds the test VM.

After a commit in `nixos-secrets`: `config update secrets` in this repository, commit, then switch.

## Updates

`config update <what>` changes the pins, shows the old and new dates of every changed input and the versions of pi and SearXNG, and runs the checks. Review with `git diff`, then `config commit "<message>"`. If the checks fail, nothing is committed; `git checkout flake.lock modules/dev/pi.nix` undoes the update.

| What | Moves |
| --- | --- |
| `pi` | pi itself (`nixpkgs-pi`). pi is built here with one change (see below), so an update builds it on this machine, in about a minute |
| `extensions` | pi's extensions to their newest versions on npm, with their hashes, in `modules/dev/pi.nix`, and the versions that the `pi-config` check expects pi to report; `pi-chatgpt-limit` is not on npm and stays |
| `search` | SearXNG (`nixpkgs-search`): when search engines stop answering |
| `system` | NixOS and everything else that is not one of the separate pins |
| `dev` | The development environments (`nixpkgs-unstable`: PETSc, CUDA). A project keeps its versions until it runs `nix flake update blocks` |
| `secrets` | The pin of `nixos-secrets`, after a commit there |
| `all` | `system`, `pi`, `extensions`, `search` and `secrets`; not `dev` |

The updater takes a version and a hash from the npm registry's answer only if they are a plain version and a sha512 hash; any other answer, or a package the registry does not know, leaves the file as it is.

## The one change to pi

All pi sessions share the login file (`~/.pi/agent/login/auth.json`), and each can write it, because a login renews itself. pi would run a value in that file that starts with `!` as a command to fetch a key. One session could so make every other session run a command. pi is therefore built with that function switched off (`modules/flake/nixpkgs.nix`): it never runs a command named in the login file, in `models.json` or in an MCP server's headers. Subscription logins and ordinary keys work as before.

After a pi update two things show whether the change still holds: the build stops if pi no longer has that function in the two places, and the `pi-login-commands` check fails if pi runs such a command.

Still possible: a session can replace or remove the shared login, which logs the other sessions out or makes them use another account.

## Validation

- `pi-login-commands`: pi, asked a question with a login file whose key is a command, does not run it; an ordinary key is still used. Control: pi as nixpkgs builds it runs the command.
- `pi-sandbox-location`: the protected files and the git hooks are refused when pi starts below a folder named `.git` that a session made inside the repository, and when the repository is shared with `--allow` or `--allow-ro` from another one; a start in the folder above the repository, and `--allow` of that folder or of a folder inside the repository, are refused with a message; the hooks of a second shared project and of a repository below the project are refused, and nothing the launcher opened reaches the session. Controls: in the repository itself; `--unlock`, also through `--allow`; an ordinary folder can be made.
- `mimir-config` and `mimir-vm-config` hold the assertions by place and by value of point 4. Tried by hand, one change at a time in a copy (`config-guard` cannot build a whole configuration): an ordinary module that leaves a folder out of the backup, opens a port or replaces a check; a port opened and a trusted Nix user added in the workstation profile; the same exclusion under a made-up file name. Each makes `mimir-config` fail. A new root service from an ordinary module does not: see the limits.
- `config-guard`, for a push, with the two hooks as git is given them: commits made through `config commit` or the commit hook are pushed without a question; a commit made with `--no-verify`, a merge, a fast-forward and a cherry-pick are each refused at the push until the content passed the checks, and then until the typed `yes` (refused on `no` and without a terminal), with the commits named; a new branch whose commits went through the guard and the removal of a branch pass.
- `config-guard`, for changed modules: a commit that changes a module is refused on `no` and without a terminal, names the module, and is accepted on `yes`.
- `pi-sandbox-protected-list`: the launcher with the real list, in copies of this repository and of the pinned `nixos-secrets`: every path the list names exists, each is refused (a file by adding a line, a folder by making a file in it), an ordinary file is changed, and with `--unlock` all are changed. It fails while the pin of `nixos-secrets` is older than a path the list names: `config update secrets`.
- `ssh-settings`, for the list of hosts: the private list may only hold settings from an agreed set; a stand-in with `ProxyCommand`, `Match exec` and `PKCS11Provider` is reported by line and setting, never by value.
- `config-guard`, for a repository of secrets: a plain value typed into an encrypted file, a plain file in a folder below `secrets/`, and a file of another kind there each fail the check (sops itself calls the first one encrypted); a new file elsewhere needs the typed `yes`, a later change of it does not.
- `pi-sandbox-direnv`: with the laptop's direnv settings, a line that a session adds to a cache file, a program it puts where nix-direnv looks first, and a flake it changes are neither run nor evaluated when the user enters the project afterwards; the cache lies outside the project. Control: with nix-direnv's own settings all three happen.
- `pi-sandbox-protected`: in a sandbox, changing, adding to, renaming, removing and replacing protected files is refused and an ordinary file can be changed. Controls: with `--unlock` all of it is accepted; the same folder under another name is not protected, and `--unlock` is refused there.
- `config-guard`, for the content that is checked and built: with files in the folder that git ignores, the stand-in for the checks receives exactly the files of the staged content, byte for byte; an ignored file below `modules/` stops the check and the commit and is named (control: accepted without it); `build`, `switch` and `install` hand the last commit's files to a stand-in for nix, and are refused while the folder differs from that commit or no check passed on it (control: accepted after `config check`).
- `config-guard`: in a scratch repository with a stand-in for the checks: no commit without a check, after a change, or after a failed check; a protected file and a new module need the typed `yes` and are refused on `no` and without a terminal; an ordinary change does not ask; another repository is refused; a secret that is not encrypted fails the check; the extension updater against a stand-in registry, including two answers it must refuse.
- Not covered by a check: `config update` against the real sources, which needs the network.
