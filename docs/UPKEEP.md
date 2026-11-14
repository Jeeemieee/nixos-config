# Upkeep: checks, guarded commits and updates

One command, `config`, keeps this repository and `nixos-secrets`. It is run by the user, outside any pi sandbox. On the workstations it is installed; elsewhere: `nix run "path:$PWD#config" -- <command>`, or the admin shell (`nix develop`).

| Command | What it does |
| --- | --- |
| `config check` | Runs the checks on the staged content and records that exactly this content passed |
| `config commit "<message>"` | Stages everything, runs the checks, asks for a typed `yes` when protected files change, commits and pushes |
| `config update <what>` | Fetches new versions, shows what changed and runs the checks; it does not commit |

In `nixos-config` the checks are `nix flake check`. In `nixos-secrets` the check is that every file below `secrets/` is encrypted.

## What an agent cannot change

Three things hold on NixOS whatever an agent is told or decides:

1. **`.git` is read-only in every pi session** (`docs/MIMIR-VM.md`, section pi): an agent cannot stage, commit or push.
2. **Protected files are read-only in a pi session** unless the user starts it with `pi --unlock`. The list is in `config-tool/protected.nix`:

   | Repository | Protected | Why |
   | --- | --- | --- |
   | `nixos-config` | `modules/dev/pi.nix`, `AGENTS.md` | What an agent's sandbox is, and its instructions |
   | | `config-tool/`, `modules/flake/config-tool.nix` | This list and the guard |
   | | `modules/flake/checks.nix`, `dev-env/checks.nix` | The checks |
   | | `modules/security/`, `modules/services/backup.nix`, `modules/storage/`, `modules/install/`, `install/`, `modules/boot/` | A wrong change loses data or access |
   | | `flake.nix`, `flake.lock` | Which versions of everything are used |
   | `nixos-secrets` | `AGENTS.md`, `.sops.yaml`, `secrets/` | Who may decrypt, and the encrypted values |

   As mounts they can neither be changed nor renamed, removed or replaced. `pi --unlock` says which files it opens, for that one session. A repository that holds an `AGENTS.override.md`, which pi would read instead of `AGENTS.md`, is refused. The protection goes with the repository's place: it is the same wherever below the repository pi starts and when the repository is shared with `--allow`, where `--unlock` opens it too.
3. **A commit passes two gates**, in `config commit` and, for a plain `git commit`, in a hook that the user's own git settings name for the two repositories (an agent only reads those settings):
   - the checks passed on exactly the staged content: a change after the check, or a failed check, stops the commit;
   - every change of a protected file, and every file added to, removed from or renamed below `modules/`, is listed and needs a typed `yes`. Before the question git itself shows what changes in those files: a summary, then the changes in its own viewer (`q` closes it). Without a terminal to ask on, the commit is refused.

Limits, stated plainly:
- **On a machine where pi runs without the sandbox** (Ubuntu before the move) none of this is enforced against an agent; `config commit` still applies the two gates to the user's own commits.
- **Every file below `modules/` is loaded**, so a new, unprotected file there can change what a protected file sets. That is why the guard asks about added and removed modules; the user's review of the commit is the last line.
- `git commit --no-verify` skips the hook. Only the user can commit, so that is his decision.
- The record of a passed check is a file in `~/.local/state/config-checks/`, a hidden folder that no sandbox sees.

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
- `pi-sandbox-protected`: in a sandbox, changing, adding to, renaming, removing and replacing protected files is refused and an ordinary file can be changed. Controls: with `--unlock` all of it is accepted; the same folder under another name is not protected, and `--unlock` is refused there.
- `config-guard`: in a scratch repository with a stand-in for the checks: no commit without a check, after a change, or after a failed check; a protected file and a new module need the typed `yes` and are refused on `no` and without a terminal; an ordinary change does not ask; another repository is refused; a secret that is not encrypted fails the check; the extension updater against a stand-in registry, including two answers it must refuse.
- Not covered by a check: `config update` against the real sources, which needs the network.
