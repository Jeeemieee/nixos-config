# Mimir: personal NixOS configuration

NixOS configuration for `jeeemieee`. Two hosts share one workstation profile: `mimir`, the laptop (not installed yet), and `mimir-vm`, a test VM that is removed once the laptop has migrated.

- **[Mimir, the laptop](docs/MIMIR.md)**: what the laptop host is made of, its hardware, and what is tested where
- **[Mimir VM](docs/MIMIR-VM.md)**: build, launch, change and validate the VM
- **[Applications](docs/APPS.md)**: installed programs and how to add more
- **[Development environments](docs/DEV-ENVIRONMENTS.md)**: per-project Python, C/C++/Fortran, PETSc and CUDA from building blocks
- **[Disk layout and snapshots](docs/DISK.md)**: the encrypted ZFS disk for physical machines, and how to restore files
- **[Backup](docs/BACKUP.md)**: the hourly restic backup of `/home` to the home server, and how to restore
- **[Installation](docs/INSTALL.md)**: installing a host from another Linux system through a virtual machine that only sees the target disk
- **[Secure Boot](docs/SECURE-BOOT.md)**: own signing keys with lanzaboote, and how to inspect and recover
- **[Secrets](docs/SECRETS.md)**: the private [nixos-secrets](https://github.com/Jeeemieee/nixos-secrets) repository and its sops-nix integration

## Layout

Every file under `modules/` is a [flake-parts](https://flake.parts) module, discovered by [import-tree](https://github.com/vic/import-tree) (the [dendritic pattern](https://github.com/mightyiam/dendritic)). Files define named NixOS or Home Manager modules, and hosts select the ones they need.

| Path | Contents |
| --- | --- |
| `modules/hosts/` | `mimir` (laptop) and `mimir-vm` (test VM): names, hardware and state versions |
| `modules/profiles/` | `workstation`: the account, desktop, applications and services of every personal machine |
| `modules/hardware/`, `modules/users/` | Laptop services, NVIDIA, DisplayLink; the login password from secrets |
| `modules/apps/` | Desktop applications, fonts and default applications |
| `modules/desktop/` | KDE Plasma and PipeWire audio |
| `modules/dev/` | VSCodium, direnv and the Git identity |
| `modules/storage/`, `modules/boot/` | Encrypted ZFS disk with snapshots, UEFI boot, Secure Boot |
| `modules/services/` | VPN clients, Wi-Fi, rootless Docker, libvirt |
| `modules/security/` | Machine age identity and sops-nix secrets |
| `modules/host-specification/` | Per-host settings (`hostSpec`) read by shared modules |
| `modules/install/`, `install/` | The installer and the `install` tool; the disk validation and its test cases |
| `dev-env/` | Building blocks for project development environments, their tests and the project template (plain Nix, not modules) |
| `modules/flake/` | Flake wiring: hosts, package set and unfree allowlist, checks, dev shell, formatter |

The dev shell (`nix develop`, or automatically through `.envrc` with direnv) provides `sops`, `age` and `ssh-to-age`.

## Acknowledgements

Started from [thmsdelange/nix-futura](https://github.com/thmsdelange/nix-futura).
