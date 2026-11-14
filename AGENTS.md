# Rules for agents working on this repository

This repository declares the user's NixOS machines. It decides what agents themselves may do, so parts of it are closed to agents. Read `README.md` first; the documents under `docs/` describe each part.

## What holds whether you follow these rules or not

- **You cannot stage, commit or push.** In a pi session the repository's `.git` is read-only. The user reviews and commits.
- **Protected files are read-only** unless the user started this session with `pi --unlock`: the pi sandbox, the checks, secrets, backup, disk layout, installer, boot, the version pins, this file, and the commit guard. The list is `config-tool/protected.nix`. If your task needs one of them, stop and say so; do not work around it.
- **Every file below `modules/` is loaded.** A new file there can change anything, including what a protected file sets. The commit guard shows the user every module that is added, removed or renamed.
- **A commit passes two gates** (`docs/UPKEEP.md`): the checks passed on exactly the content being committed, and the user typed yes to every change of a protected file.

## How to work here

- Propose before you build: the goal, what changes, what does not, the acceptance criteria fixed in advance, and the approaches with their trade-offs. Wait for the user's approval.
- For a fault: reproduce it first with a test that fails, state the cause, then make the smallest change that makes the test pass.
- **Never weaken a check.** A check that is itself wrong is corrected with the reason stated. A new check gets a control that shows it can fail.
- Nothing unsupported falls back silently: refuse with a message that says what to do.
- No secret, password, private address or project name in this repository. Private values belong in the `nixos-secrets` input; never read decrypted secrets.
- Test in virtual machines or in the Nix build, never on the user's disks. Never run `nix-collect-garbage`.
- Run the checks with `nix flake check "path:$PWD"`. On a machine without flakes enabled, add `--extra-experimental-features 'nix-command flakes'`.
- Write for a reader who is new to Nix: British English, short sentences, comments that say why.

## Where things are

| Path | Contents |
| --- | --- |
| `modules/` | Every file is a flake-parts module; `host-<name>` modules become machines |
| `modules/profiles/workstation.nix` | What every personal machine gets |
| `modules/flake/checks.nix` | The policies every machine must meet |
| `dev-env/`, `install/`, `config-tool/` | Plain files, not modules: development environments, the installer's disk validation, the upkeep command |
| `docs/` | One document per part; update it with the change |
