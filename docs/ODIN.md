# Odin, the gaming desktop

`modules/hosts/odin/default.nix` defines the hardware-independent part of the physical gaming desktop. It is prepared but deliberately not installable yet: the real disk path, ZFS host ID, network-device names and private input files must be supplied first. [ODIN-INSTALL.md](ODIN-INSTALL.md) records that preparation and the NixOS-first installation order.

## What it is made of

| Module | Contents | Shared with |
| --- | --- | --- |
| `nixos.workstation` | The account, KDE Plasma, ordinary applications, VPN clients, Wi-Fi, rootless Docker, libvirt and development tools; see [APPS.md](APPS.md) | `mimir`, `mimir-vm` |
| `nixos.gaming` | Steam, Proton-GE, Gamescope, GameMode, MangoHud, Heroic, Lutris, Ludusavi, AMD/Mesa graphics and the Windows reboot entry | Odin only |
| `nixos.login-password` | The login password from `secrets/shared.yaml`; accounts are immutable | Physical machines |
| `nixos.disk`, `nixos.boot` | A 2 GiB EFI partition, a real 200 GiB unallocated Windows gap, random-key swap and encrypted ZFS; see [DISK.md](DISK.md) | Physical machines, with host-specific geometry |
| `nixos.secure-boot` | Locally generated Secure Boot keys while retaining Microsoft's keys; see [SECURE-BOOT.md](SECURE-BOOT.md) | Physical machines |
| `nixos.backup` | Hourly append-only backup of valuable data below `/home`; see [BACKUP.md](BACKUP.md) | Physical machines, with separate credentials |
| `nixos.tailscale-ssh-server` | Key-only SSH for `jeeemieee`, admitted only through the `tailscale0` firewall interface | Odin only |

Odin does not import the worker subsystem, NVIDIA, DisplayLink or laptop hardware. The shared disk recipe still creates the two root-owned worker mount points, with a 1 GiB quota on `~/workers`, but no worker service uses them.

## Facts still required

The production host keeps these values explicit under `hostSpec.odin`:

- `systemDiskById`: the exact `/dev/disk/by-id/...` target accepted by the installer
- `hostId`: eight hexadecimal digits for ZFS
- `networkDevices`: the physical interface names observed on Odin

The private input must also contain:

- `ssh/odin_authorized_keys`, containing the public half of the Bitwarden-held SSH key
- `secrets/odin.yaml`, containing Odin's own `tailscale_authkey`, `restic_env` and `restic_password`

`config install start odin` refuses before creating an image or touching a disk while any item is absent. Synthetic facts and generated credentials exist only in the automated checks.

## Gaming and graphics

The kernel's `amdgpu` driver and Mesa RADV serve both 64-bit and 32-bit applications. Redistributable firmware is enabled. AMDVLK, proprietary AMD OpenGL, ROCm and GPU bus IDs are not added.

Steam supplies Valve Proton. Proton-GE is installed as an explicit compatibility alternative, not forced globally. Gamescope and GameMode are enabled; MangoHud is installed for diagnosis. Heroic and Lutris keep their own launcher state and prefixes. Bottles and Steam Remote Play ports are not enabled.

Downloaded game libraries are not backup data. Odin excludes Steam's normal `steamapps` locations and `~/Games` from restic. A future separate game disk should be mounted outside `/home`; a custom library placed elsewhere below `/home` must be added to the exclusions first.

## Save export

A persistent user timer runs Ludusavi daily, with up to 30 minutes of random delay:

```bash
systemctl --user status ludusavi-backup.timer
systemctl --user start ludusavi-backup.service
journalctl --user -u ludusavi-backup.service
```

Exports go to `~/game-saves/ludusavi`. That folder is below `/home`, outside every backup exclusion, and is therefore included in the hourly restic backup. Check its contents after adding or updating a game: neither cloud support nor a successful Ludusavi process proves that a particular save was discovered.

## Reboot into Windows

Plasma receives a **Reboot into Windows** application entry. It invokes:

```bash
systemctl reboot --boot-loader-entry=auto-windows
```

Systemd asks for the normal authenticated reboot permission, then selects Windows for one boot only. The entry works after Windows has placed its boot manager in the shared EFI partition and systemd-boot has discovered `auto-windows`.

## Remote access

OpenSSH listens normally because a changing Tailscale address cannot be bound by interface name. The firewall is the boundary:

- no global incoming port is opened
- TCP 22 is allowed only on `tailscale0`
- password and keyboard-interactive authentication are disabled
- root login is refused
- only `jeeemieee` is allowed
- the approved public key comes from `ssh/odin_authorized_keys`

The private key remains in Bitwarden's SSH agent on the client. Add Odin's Tailscale name and user to the private `ssh/config`; no private address belongs in this repository.

## Validation

Automated checks cover the exact host composition, package and unfree policy, the real partition gap, the complete system closure, the daily save timer, backup placement, installer refusals and key-only SSH from a simulated `tailscale0` network while an ordinary LAN cannot reach port 22.

The checks cannot validate the real AMD GPU, Vulkan or 32-bit rendering, firmware menus, monitors, controllers, Windows boot behaviour, anti-cheat, game compatibility or the physical network interfaces. After installation, record at least:

```bash
vulkaninfo --summary
glxinfo -B
systemctl --user start ludusavi-backup.service
sudo sbctl status
bootctl status
tailscale status
```

Also start one native game, one Proton game, Gamescope, GameMode and MangoHud; test every controller in Steam; restore one Ludusavi export from restic; and prove SSH succeeds over Tailscale but not over the ordinary LAN.
