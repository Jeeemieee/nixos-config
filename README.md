# Mimir: personal NixOS configuration

NixOS configuration for `jeeemieee`. The only host is `mimir-vm`, a KDE Plasma trial in a local QEMU VM that will become the configuration for the laptop `mimir`.

- **[Mimir VM](docs/MIMIR-VM.md)**: build, launch, change and validate the VM
- **[Applications](docs/APPS.md)**: installed programs and how to add more
- **[Disk layout and snapshots](docs/DISK.md)**: the encrypted ZFS disk for physical machines, and how to restore files
- **[Secrets](docs/SECRETS.md)**: the private [nixos-secrets](https://github.com/Jeeemieee/nixos-secrets) repository and its sops-nix integration

## Layout

Every file under `modules/` is a [flake-parts](https://flake.parts) module, discovered by [import-tree](https://github.com/vic/import-tree) (the [dendritic pattern](https://github.com/mightyiam/dendritic)). Files define named NixOS or Home Manager modules, and hosts select the ones they need.

| Path | Contents |
| --- | --- |
| `modules/hosts/mimir-vm/` | The VM host: account, locale, virtual hardware, selected modules |
| `modules/apps/` | Desktop applications, fonts and default applications |
| `modules/desktop/` | KDE Plasma and PipeWire audio |
| `modules/dev/` | VSCodium, direnv and the Git identity |
| `modules/storage/`, `modules/boot/` | Encrypted ZFS disk with snapshots, UEFI boot |
| `modules/services/` | VPN clients, Wi-Fi, rootless Docker, libvirt |
| `modules/security/` | Machine age identity and sops-nix secrets |
| `modules/host-specification/` | Per-host settings (`hostSpec`) read by shared modules |
| `modules/flake/` | Flake wiring: hosts, package set and unfree allowlist, checks, dev shell, formatter |

The dev shell (`nix develop`, or automatically through `.envrc` with direnv) provides `sops`, `age` and `ssh-to-age`.

## Acknowledgements

Started from [thmsdelange/nix-futura](https://github.com/thmsdelange/nix-futura).
