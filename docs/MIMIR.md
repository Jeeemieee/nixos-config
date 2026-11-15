# Mimir, the laptop

`modules/hosts/mimir/default.nix` defines the laptop: a Dell Precision 7680 (Intel i7-13850HX, 32 GiB RAM, Intel graphics with an NVIDIA RTX 3500 Ada). It is not installed yet; the installation is rehearsed in a virtual machine first.

## What it is made of

| Module | Contents | Shared with |
| --- | --- | --- |
| `nixos.workstation` (`modules/profiles/workstation.nix`) | The account, KDE Plasma, applications, VPN clients, Wi-Fi, rootless Docker, libvirt, the development tools; see [APPS.md](APPS.md) | `mimir-vm`, and later the desktop |
| `nixos.login-password` | The login password from nixos-secrets; accounts cannot be changed outside the configuration | Later the desktop |
| `nixos.disk`, `nixos.boot` | Encrypted ZFS with snapshots, UEFI boot; see [DISK.md](DISK.md) | Physical machines |
| `nixos.secure-boot` | Secure Boot with own keys; see [SECURE-BOOT.md](SECURE-BOOT.md) | Physical machines |
| `nixos.laptop` | Firmware for Wi-Fi, Bluetooth, audio and graphics; Bluetooth; Thunderbolt dock authorisation (bolt); disk-health monitoring (smartd) with desktop warnings | Laptops |
| `nixos.nvidia-offload` | The NVIDIA driver with the open kernel modules, used on demand | Machines with a second GPU |
| `nixos.displaylink` | The Dell D3100 dock (DisplayLink) | Machines using such a dock |
| `nixos.backup` | The hourly backup of `/home` to the home server; see [BACKUP.md](BACKUP.md) | Machines with their own backup credentials |
| `nixos.workers` | Several pi agents at once: a copy, a folder and a scratch area per worker, the job queue, roles, and the limits on memory and cores; see [WORKERS.md](WORKERS.md) | Machines with the two workers datasets of `nixos.disk` |

The host itself only adds its name, its ZFS host ID, the GPU bus addresses, Intel microcode and thermal daemon, the 3Dconnexion SpaceMouse driver (`spacenavd`), the USB storage drivers for the first boot stage (the system disk starts out in a USB enclosure) and its state versions. `hostSpec.disk.device` is deliberately unset: the disk is chosen, and confirmed by its serial number, when the laptop is installed (see [INSTALL.md](INSTALL.md)); the installed system finds its partitions by label.

## Graphics

The Intel GPU drives the desktop and the NVIDIA GPU sleeps until something uses it, which saves battery. To run a program on the NVIDIA GPU: `nvidia-offload <program>`. CUDA programs use it without that: the driver's libraries are in `/run/opengl-driver/lib`, where the CUDA build of PETSc looks for `libcuda.so.1` and `libnvidia-ml.so.1`.

## The dock driver

DisplayLink's driver is unfree and cannot be downloaded by Nix, because its licence has to be accepted. Once per driver version (the build prints this when the file is missing):

```bash
nix-prefetch-url --name displaylink-620.zip 'https://www.synaptics.com/sites/default/files/exe_files/2025-09/DisplayLink%20USB%20Graphics%20Software%20for%20Ubuntu6.2-EXE.zip'
```

The file must be in the Nix store of the machine that builds the system; a garbage collection can remove it while no built system refers to it.

## Unfree software

The NVIDIA user-space driver (`nvidia-x11`, `nvidia-settings`) and `displaylink` are on the allowlist in `modules/flake/nixpkgs.nix`, next to the applications.

## Secrets at the first boot

The login password is decrypted while the accounts are created, earlier than the other secrets. The laptop's age key must therefore be on its disk and enrolled in nixos-secrets before the first boot; otherwise the account has no password. The installation generates the key on the target disk, and refuses to install a system whose secrets that key cannot decrypt; see [INSTALL.md](INSTALL.md).

## Validation

- `mimir-config` asserts the workstation policies that also hold for the VM (no auto-login, one account, locked root, sudo with a password, no SSH server, firewall, rootless Docker, the editor, browser and mail settings, Wi-Fi placeholders, the unfree allowlist), and for the laptop: the password only from secrets with immutable accounts, ZFS inside LUKS for everything but the EFI partition, swap with a random key, Secure Boot with Microsoft's keys kept, the NVIDIA and DisplayLink drivers, Bluetooth and smartd
- `mimir-system` builds the whole system, including the NVIDIA and DisplayLink drivers and the encrypted secrets' manifests
- `disk-layout` and `secure-boot` test the disk layout and Secure Boot in virtual machines

Not testable in a virtual machine, to be checked on the laptop after the installation: the NVIDIA GPU (`nvidia-smi`, `nvidia-offload`, CUDA), the dock and external screens, suspend and resume, Bluetooth, Wi-Fi and eduroam, the internal screen's scaling, the touchpad, audio, the webcam, and the firmware's Secure Boot setup mode.

Also on the laptop only: a container with the graphics card (`docker run --rm --device nvidia.com/gpu=all <image> nvidia-smi`; containers from Ubuntu have to be created again); the touchpad (natural scrolling, tap to click, off while typing, right click in the bottom-right corner) and the mouse on the 3Dconnexion receiver (no acceleration), which Plasma sets per device; and the panel on every screen with the dock connected.

Also to be checked on the laptop, because Ubuntu catches these keys before the user's VM window sees them (they pass in the automated test VM): `Meta+<number>` and `Meta+Shift+<number>` for the desktops, and `Alt+Space` with a web keyword such as `nixopt:programs.tmux`; and whether the KDE wallet asks for a password when Brave is opened. Also whether pipewire and KDE's crash reporter crash at logout, as they did in a virtual machine without a sound card.

### Checked on the laptop

One row per check of the three paragraphs above, added when the user ran it on the installed laptop.

| Date | Check | Result |
| --- | --- | --- |
| 2026-11-15 | `nvidia-smi` | Passed: driver 595.71.05 sees the RTX 3500 Ada with 12 282 MiB. It printed a power draw of 593 W for a 90 W card, which cannot be right; to be looked at again with `nvidia-offload`. Later the kernel log showed `NVRM: _kgspProcessRpcEvent: Attempted to process RPC event from GPU0: 0x101a (PFM_REQ_HNDLR_STATE_SYNC_CALLBACK) during bootup without API lock` with a failed assertion in `kernel_gsp.c:1447`, twice, when the card woke up; whether that matters is open |
| 2026-11-15 | The first `config switch` on the laptop | Passed on the second try, with the kernel's messages watched (`sudo dmesg -w`): no message about the disk. The first try is the freeze below |
| 2026-11-15 | GitHub through the key in Bitwarden | Passed: `git push` reached GitHub once Bitwarden was open, unlocked and its "Enable SSH agent" switch was on. That switch is off on a new machine; until then git answers `Permission denied (publickey)` |
| 2026-11-15 | The backup ([BACKUP.md](BACKUP.md)) | Passed: a run started by hand saved snapshot `adf62626` in 9 seconds (23 906 files, 1.157 GiB), on top of an earlier snapshot of this laptop, so the secret values are right. The restore of one file with a byte-for-byte comparison: reported as passed by the user; its output was not recorded |
| 2026-11-15 | `~/workers` in the backup | Passed: snapshot `c3377001` is of `/home` and `/home/jeeemieee/workers`, and lists a folder made by hand below `~/workers` |
| 2026-11-15 | The worker tools with the real pi ([WORKERS.md](WORKERS.md)) | Passed, in a scratch project, by a protocol of twelve steps written beforehand: nix in a sandbox; a manager, an implementer before and after the user's approval, a reviewer and a deep reviewer, each reading and writing what its role allows; the merge, the whole suite, `workers take` and the user's commit; the live overview; the to-do list of a real session; the removals, the manager's without `--force`; a refused start on branch `old`. One step failed first: the implementer did not commit in its own copy, because the user's general rules forbade every commit. The rule now names his own repositories only, and the role texts say that a worker commits in its copy |
| 2026-11-15 | Starting without F12 | Reported by the user: the USB disk is first in the firmware's boot order, set from Ubuntu. To be looked at again when the disk moves into the laptop. A firmware password is not set yet; without one Secure Boot means little |

### Open: the freeze of 2026-11-15

At about 13:19 the laptop stopped responding, moments after a commit and as `config switch` was started: the pointer moved, programs failed, and it needed the power button. Known so far:

- The log on the disk ends at 13:18:49, although the laptop ran for minutes more. Its last lines are the firmware service (`fwupd`), which failed to open two USB devices on port 2 of the controller that also carries the system disk (port 1).
- The system disk is the SSD in the USB enclosure (Realtek RTL9210, `0bda:9210`, driver `uas`). At start the kernel reports `enable of device-initiated U1 failed` for it. No reset or I/O error is recorded before the freeze.
- `config switch` is cleared: repeated with the kernel's messages watched, it finished without a message about the disk.
- The firmware service is cleared: `fwupd.service` restarted and `fwupd-refresh.service` started by hand, with the kernel's messages watched, caused no freeze and no message about the disk.

The cause is not known. A disk that dropped off USB fits what was seen and is not proven. It happened once.
