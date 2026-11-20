# Disk layout and snapshots

`modules/storage/disk.nix` defines `nixos.disk`: the encrypted ZFS system disk for physical machines, with its snapshot policy. `modules/boot/uefi.nix` defines `nixos.boot`: UEFI boot with systemd-boot. The physical hosts `mimir` and `odin` use them; the test VM `mimir-vm` keeps its own simple disk.

## Physical layouts

| Host | EFI (`/boot`) | After EFI | Swap | Encrypted system |
| --- | --- | --- | --- | --- |
| `mimir` | 1 GiB | No gap | 32 GiB, new random key at every boot | LUKS container `crypt` in all remaining space, holding ZFS pool `rpool` |
| `odin` | 2 GiB | 200 GiB genuinely unallocated for a later Windows installation | 32 GiB, new random key at every boot | LUKS container `crypt` in all remaining space, holding the same ZFS recipe |

Odin is installed **NixOS first** with the existing destructive whole-disk installer. Disko gives swap an explicit start after the gap; no temporary partition occupies it. Windows 11 is installed second and may create only its Microsoft reserved, Windows and recovery partitions in that unallocated extent. See [ODIN-INSTALL.md](ODIN-INSTALL.md). Neither host supports hibernation.

## ZFS datasets

| Dataset | Mounted at | Snapshots (sanoid) |
| --- | --- | --- |
| `rpool/root` | `/` | Daily, kept 7 days |
| `rpool/nix` | `/nix` | None: rebuilt from the configuration. Limited to `nixQuota` |
| `rpool/home` | `/home` | Hourly for 48 hours, daily for 30 days, monthly for 6 months. `homeReservation` is kept for it whatever else fills |
| `rpool/scratch` | `~/scratch` of `hostSpec.disk.scratchUser` | None; limited to `scratchQuota`, the workers' areas included |
| `rpool/scratch/workers` | `~/scratch/workers` | None. Raw output of agent workers; the top folder belongs to root |
| `rpool/workers` | `~/workers` | Hourly for 24 hours, daily for 7 days, also for every dataset created below it. Agent workers' copies of projects, reports and sessions; limited to `workersQuota`; the top folder belongs to root |

The sizes are options of `hostSpec.disk` without defaults, because they depend on the disk. On `mimir` (2 TB, 1863 GiB; about 1770 GiB usable after the boot partition, swap and ZFS's own reserve of a thirty-second of the pool): 600 GiB reserved for `/home`, at most 250 GiB for the Nix store, 600 GiB for scratch and 200 GiB for `~/workers`. If every limit were reached while `/home` is at its reservation, about 120 GiB would be left.

On `odin`, for the approved 1 TB plan after the 2 GiB EFI partition, 200 GiB Windows gap and 32 GiB swap: 200 GiB is reserved for `/home`, `/nix` is limited to 150 GiB, scratch to 275 GiB, and the unused shared workers dataset to 1 GiB. The game-disk layout is deliberately not declared yet.

The ZFS disk is not split: a limit is the most a dataset may grow to, and unused space stays available to the others; the reservation is a minimum, and `/home` can grow beyond it.

The two workers datasets hold what the worker tools create ([WORKERS.md](WORKERS.md)): below `rpool/workers` a dataset per worker with its own limit, and below `rpool/scratch/workers` a scratch area per worker with its own limit. Their top folders belong to root, so that nothing running as the user can rename or replace what is mounted below them; the user cannot create folders there without `sudo`.

What agents write outside those datasets, and what limits it:

| Place | Dataset | Limit |
| --- | --- | --- |
| The project of an ordinary `pi` session, which the session writes directly | `rpool/home` | None of its own: it is your own folder |
| pi's session files of ordinary sessions, `~/.pi/agent/sessions/` | `rpool/home` | None |
| The tools' own records, `~/.local/state/workers/` and `~/.local/state/workers-plain/` | `rpool/home` | None by the disk. An ordinary session's run records are kept within about 2 MiB; the tools' copy of the workers' commits holds what the workers' branches hold and no more |
| All workers' scratch areas together | `rpool/scratch/workers` | Each area has its own limit. Together they count against `scratchQuota`, so they can use up what your own `~/scratch` output would need; a limit of their own for the whole is not set | `~/workers` is in the backup with every file system mounted below it ([BACKUP.md](BACKUP.md)); `~/scratch/workers` is not.

All datasets use zstd compression and no access-time updates. ZFS's cache is capped at 4 GiB. The pool is scrubbed monthly (every block is read and its checksum verified) and trimmed weekly.

The disk passphrase is typed at every boot. It is not in nixos-secrets, which live on the encrypted disk. The boot waits for it as long as it takes: the pool is imported only after the encrypted container is open. (Without that order NixOS lets the import retry for one minute beside the prompt, and a passphrase typed later ended in the emergency mode; the `disk-layout` check types it after 75 seconds.) `hostSpec.disk.device` normally has no default and the formatting script cannot be built without it; the installer sets it to the one disk it can see (see [INSTALL.md](INSTALL.md)). Odin keeps its real target under `hostSpec.odin.systemDiskById` and the installer refuses until it is set and matches the selected disk. The installed systems find their partitions by label, not by device name.

## Snapshots are not backups

Snapshots live on the same disk: they undo deletions and overwrites, and are lost with the disk. The backup is a separate copy on the home server: see [BACKUP.md](BACKUP.md).

Restore a file from a snapshot of `/home`:

```bash
ls /home/.zfs/snapshot/
cp /home/.zfs/snapshot/<snapshot>/<user>/<path> ~/<path>
```

List snapshots and the space they hold: `zfs list -t snapshot -o name,used,refer`. A deleted file keeps its space until the last snapshot containing it expires, which is why simulation output belongs in `~/scratch`.

## Change the layout later

- A limit or the reservation: the option in the host's `hostSpec.disk`, and at once on the running system with `sudo zfs set quota=<size> rpool/<dataset>` or `sudo zfs set reservation=<size> rpool/home`
- Another dataset with its own policy: add it under `datasets` in `disk.nix`, and under `services.sanoid.datasets` if it needs snapshots. On an installed system it is created with `sudo zfs create`, with the same options, before rebuilding; disko only applies the layout when the disk is formatted
- Snapshot retention: the `templates` in `disk.nix`

## Validation

The `disk-layout` check (`nix flake check`) uses disko's install test: in a virtual machine it formats an empty disk with the ordinary layout, installs a minimal system, boots it from that disk with UEFI, types the test passphrase at the prompt, and checks that

1. the pool is healthy and sits on the opened LUKS container
2. the six datasets are mounted, compressed and without access-time updates
3. swap is active on a dm-crypt device with a random key
4. sanoid snapshots `/home` and `/`, and a deleted file is restored from the snapshot
5. scratch, the workers' areas in it and `/nix` have no snapshots; the limits and the reservation are set; scratch is writable by its user
6. the cache cap is set, and scrub and TRIM are scheduled
7. the two workers folders belong to root, and the user can neither create something in them nor rename them (control: he can do both with a folder of his own)
8. a dataset created later below `rpool/workers` gets snapshots without a rule of its own; one below scratch gets none

`odin-disk-layout` reuses that complete install-and-boot test with Odin's 2 GiB EFI partition and a smaller stand-in gap. It reads the GPT and independently proves that only EFI, swap and LUKS partitions exist and that the sectors between EFI and swap are unallocated. `odin-config` separately asserts the production 200 GiB gap and the exact swap start.

The tests take about six minutes each on this machine, because Nix's build users cannot use KVM here; results are cached until the layout changes. Their installer machine prints a `boot.zfs.forceImportRoot` warning: that is disko's throwaway installer, the installed system sets it to `false`.

Not covered by the checks: the real disks and firmware, the Windows installer, Secure Boot with both operating systems, or a full game workload. Those require the installation rehearsal and the physical desktop.
