# Disk layout and snapshots

`modules/storage/disk.nix` defines `nixos.disk`: the encrypted ZFS system disk for physical machines, with its snapshot policy. `modules/boot/uefi.nix` defines `nixos.boot`: UEFI boot with systemd-boot. No host uses them yet; the laptop host `mimir` will. The fast test VM `mimir-vm` keeps its own simple disk.

## Layout

| Part | Size | Contents |
| --- | --- | --- |
| EFI partition (`/boot`) | 1 GiB | Boot loader, kernels; not encrypted |
| Swap | `hostSpec.disk.swapSize`, default 32 GiB | Encrypted with a new random key at every boot; no hibernation |
| LUKS container `crypt` | The rest | ZFS pool `rpool` |

| Dataset | Mounted at | Snapshots (sanoid) |
| --- | --- | --- |
| `rpool/root` | `/` | Daily, kept 7 days |
| `rpool/nix` | `/nix` | None: rebuilt from the configuration |
| `rpool/home` | `/home` | Hourly for 48 hours, daily for 30 days, monthly for 6 months |
| `rpool/scratch` | `~/scratch` of `hostSpec.disk.scratchUser` | None; limited to `hostSpec.disk.scratchQuota`, default 1 TiB |

All datasets use zstd compression and no access-time updates. ZFS's cache is capped at 8 GiB. The pool is scrubbed monthly (every block is read and its checksum verified) and trimmed weekly.

The disk passphrase is typed at every boot. It is not in nixos-secrets, which live on the encrypted disk. A host sets `hostSpec.disk.device` to the disk's `/dev/disk/by-id` path; there is no default, and the formatting script cannot be built without it.

## Snapshots are not backups

Snapshots live on the same disk: they undo deletions and overwrites, and are lost with the disk. Backups are a separate step (restic).

Restore a file from a snapshot of `/home`:

```bash
ls /home/.zfs/snapshot/
cp /home/.zfs/snapshot/<snapshot>/<user>/<path> ~/<path>
```

List snapshots and the space they hold: `zfs list -t snapshot -o name,used,refer`. A deleted file keeps its space until the last snapshot containing it expires, which is why simulation output belongs in `~/scratch`.

## Change the layout later

- Scratch limit: `hostSpec.disk.scratchQuota`, or at once with `sudo zfs set quota=<size> rpool/scratch`
- Another dataset with its own policy: add it under `datasets` in `disk.nix`, and under `services.sanoid.datasets` if it needs snapshots. On an installed system it is created with `sudo zfs create`, with the same options, before rebuilding; disko only applies the layout when the disk is formatted
- Snapshot retention: the `templates` in `disk.nix`

## Validation

The `disk-layout` check (`nix flake check`) uses disko's install test: in a virtual machine it formats an empty disk with this layout, installs a minimal system, boots it from that disk with UEFI, types the test passphrase at the prompt, and checks that

1. the pool is healthy and sits on the opened LUKS container
2. the four datasets are mounted, compressed and without access-time updates
3. swap is active on a dm-crypt device with a random key
4. sanoid snapshots `/home` and `/`, and a deleted file is restored from the snapshot
5. scratch and `/nix` have no snapshots, scratch has its limit and is writable by its user
6. the cache cap is set, and scrub and TRIM are scheduled

The test takes about six minutes on this machine, because Nix's build users cannot use KVM here; the result is cached until the layout changes. Its installer machine prints a `boot.zfs.forceImportRoot` warning: that is disko's throwaway installer, the installed system sets it to `false`.

Not covered by the check: the real disk and firmware, Secure Boot, and a full desktop system on this layout; those are tested in the install rehearsal.
