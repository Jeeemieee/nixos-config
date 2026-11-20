# Backup

`nixos.backup` (`modules/services/backup.nix`) backs up the whole of `/home` to the home server with [restic](https://restic.net), every hour, also on battery. `mimir` and `odin` import it with separate append-only credentials; the VM never writes into the real backup.

Snapshots on a system disk ([DISK.md](DISK.md)) undo mistakes within days; the backup is the copy that survives loss of the machine.

## How it works

- **What:** everything under `/home`, so a new folder is backed up without being listed. Left out is only what can be rebuilt or was already thrown away:

  | Pattern | Reason |
  | --- | --- |
  | `/home/*/scratch` | Simulation output that can be recreated |
  | `/home/*/.cache` | Caches, rebuilt by their programs |
  | `/home/*/.local/share/Trash` | Files that were already deleted |
  | `/home/*/.local/share/docker` | Rootless Docker's images, containers and volumes |
  | `/home/*/.local/share/Steam/steamapps`, `/home/*/.steam/steam/steamapps` | Odin only: Steam downloads and Proton prefixes, downloaded or recreated again |
  | `/home/*/Games` | Odin only: the default Heroic and Lutris game libraries; valuable saves are exported separately |
  | `.direnv`, `.venv`, `node_modules` | Development environments, rebuilt from their definition files |
  | `__pycache__`, `.pytest_cache`, `.ipynb_checkpoints` | Python and Jupyter by-products |
  | Folders with a `CACHEDIR.TAG` file | They mark themselves as a cache |
  | Other file systems under `/home` | Network drives, a mounted backup, and `~/scratch`. The one exception is `~/workers` ([DISK.md](DISK.md)): before every run the backup lists `~/workers` and every file system mounted below it, which is each agent worker's folder, and backs them up as well. If that list cannot be made, the run fails |

  `.pi` folders in projects are kept: they hold unmerged work. Nothing outside `/home` is backed up; the system is rebuilt from this repository. On Odin, `~/game-saves/ludusavi` is deliberately kept, while Windows and every library mounted outside `/home` are outside the backup. Valuable simulation results belong under `/home`, not `~/scratch`.
- **Where:** the home server's rest-server, reached through Tailscale only. Its address and each machine's credentials are the secrets `restic_env` and `restic_password` in `secrets/<hostname>.yaml` of nixos-secrets ([SECRETS.md](SECRETS.md)). Mimir and Odin use separate rest-server logins and restic keys.
- **Each client can only add.** The server runs in append-only mode: with a machine's credentials a snapshot cannot be deleted or changed, so a compromised client cannot destroy the backup. How long snapshots are kept, pruning and integrity checks are the server's jobs; the module sets none of them.
- **Away from the server:** before every run the unit waits up to a minute for the server. No route means the run is skipped quietly. No route while the last successful backup is more than 24 hours old is a failure.
- **Failures** show as a desktop notification ("Backup failed") and in `systemctl --failed`. Wrong credentials, secrets that cannot be decrypted and an address that is not a rest-server are failures, never skipped.

## Use

```bash
systemctl status restic-backups-home.service   # the last run
systemctl list-timers restic-backups-home      # the next run
sudo systemctl start restic-backups-home       # back up now
sudo restic-home snapshots --host <mimir-or-odin> --path /home
```

Restore one file or folder into an empty place, then compare and move it:

```bash
sudo restic-home restore latest --host <mimir-or-odin> --path /home --target /tmp/restore --include /home/jeeemieee/<path>
```

The snapshots made on Ubuntu stay in the same repository under their own paths (`restic-home snapshots --host mimir` lists all); unchanged files are not uploaded twice.

## After an installation

1. Check the first run: `systemctl status restic-backups-home.service`. It reads every file once and can take hours; later runs only read what changed. Suspending or powering off interrupts a run, and the next one continues.
2. Restore one file as in [Use](#use) and compare it with the original.
3. On Odin, run `systemctl --user start ludusavi-backup.service`, verify files exist below `~/game-saves/ludusavi`, run the backup, restore one exported file and compare it byte for byte.
4. On Odin, confirm a known file below each game-library exclusion is absent from `restic-home ls latest`, while the Ludusavi export is present.
5. Watch the first days for false alarms: restic reports an error when a file disappears while it is being read, although the snapshot is saved.

## Restore after a lost machine

1. In the Tailscale admin console, remove the lost machine.
2. On the server, change that machine's rest-server password and remove its restic key (`restic key list`, `restic key remove <id>`). Update Bitwarden.
3. On the replacement machine, install restic and Tailscale and join the tailnet.
4. Take from Bitwarden the rest-server login and the repository password that is not the lost laptop's.
5. `export RESTIC_REPOSITORY='rest:http://<server>:8000/<login>/' RESTIC_REST_USERNAME=<login>`, then `read -rs RESTIC_REST_PASSWORD; export RESTIC_REST_PASSWORD`.
6. `restic snapshots --host <hostname> --path /home`, then `restic restore latest --host <hostname> --path /home --target /mnt/restore`; check it and move the files into place.
7. For a new NixOS installation, give it its own rest-server login and key: `restic key add --host <hostname>` from a machine that has access, and store `restic_env` and `restic_password` in its `secrets/<hostname>.yaml`.

If the server is lost as well, there is no second copy yet.

## Validation

The check `backup` runs the module in two virtual machines, against a throwaway rest-server of the same kind (append-only, one private repository per login), with real sops decryption of test secrets:

| Test | Expected |
| --- | --- |
| Backup, then restore of a known file | Byte-identical (SHA-256 fixed beforehand) |
| Excluded places | Absent from the snapshot; their neighbours present |
| `~/workers` as a file system of its own, with a folder made by hand and a worker's folder mounted below it | Both in the snapshot. On the module without the list the test fails: missing from the snapshot |
| No route | Skipped quietly; with a route the next run succeeds; no route and a backup older than 24 hours fails |
| Wrong repository password; secrets that cannot be decrypted | The unit fails and the notification is sent |
| Delete with the laptop's login | Refused with 403; the snapshot is still on the server |
| An address that is not a rest-server | Refused before anything is sent |

`odin-config` additionally proves that the daily Ludusavi destination is below `/home`, is not excluded, and that Odin's three declared game-library paths are excluded without changing Mimir's list.

Not tested there: the real server and Tailscale, suspend and resume, the pop-up itself in Plasma, the size and duration with a real home folder, whether Ludusavi recognises each installed game, and any custom game-library path not declared in the exclusions.
