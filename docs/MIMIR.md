# Mimir, the laptop

`modules/hosts/mimir/default.nix` defines the laptop: a Dell Precision 7680 (Intel i7-13850HX, 32 GiB RAM, Intel graphics with an NVIDIA RTX 3500 Ada). It is not installed yet; the installation is rehearsed in a virtual machine first.

## What it is made of

| Module | Contents | Shared with |
| --- | --- | --- |
| `nixos.workstation` (`modules/profiles/workstation.nix`) | The account, KDE Plasma, applications, VPN clients, Wi-Fi, rootless Docker, libvirt, the development tools; see [APPS.md](APPS.md) | `mimir-vm`, and later the desktop |
| `nixos.login-password` | The login password from nixos-secrets; accounts cannot be changed outside the configuration | Later the desktop |
| `nixos.disk`, `nixos.boot` | Encrypted ZFS with snapshots, UEFI boot; see [DISK.md](DISK.md) | Physical machines |
| `nixos.secure-boot` | Secure Boot with own keys; see [SECURE-BOOT.md](SECURE-BOOT.md) | Physical machines |
| `nixos.laptop` | Firmware for Wi-Fi, Bluetooth, audio and graphics; Bluetooth; disk-health monitoring (smartd) with desktop warnings | Laptops |
| `nixos.nvidia-offload` | The NVIDIA driver with the open kernel modules, used on demand | Machines with a second GPU |
| `nixos.displaylink` | The Dell D3100 dock (DisplayLink) | Machines using such a dock |

The host itself only adds its name, its ZFS host ID, the GPU bus addresses, Intel microcode and its state versions. `hostSpec.disk.device` is deliberately unset: the disk is named, by model and serial number, when the laptop is installed, and the formatting script cannot be built before that.

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

The login password is decrypted while the accounts are created, earlier than the other secrets. The laptop's age key must therefore be on its disk and enrolled in nixos-secrets before the first boot; otherwise the account has no password. The installation generates the key on the target disk and enrolls it before the system is installed; see [SECRETS.md](SECRETS.md).

## Validation

- `mimir-config` asserts the workstation policies that also hold for the VM (no auto-login, one account, locked root, sudo with a password, no SSH server, firewall, rootless Docker, the editor, browser and mail settings, Wi-Fi placeholders, the unfree allowlist), and for the laptop: the password only from secrets with immutable accounts, ZFS inside LUKS for everything but the EFI partition, swap with a random key, Secure Boot with Microsoft's keys kept, the NVIDIA and DisplayLink drivers, Bluetooth and smartd
- `mimir-system` builds the whole system, including the NVIDIA and DisplayLink drivers and the encrypted secrets' manifests
- `disk-layout` and `secure-boot` test the disk layout and Secure Boot in virtual machines

Not testable in a virtual machine, to be checked on the laptop after the installation: the NVIDIA GPU (`nvidia-smi`, `nvidia-offload`, CUDA), the dock and external screens, suspend and resume, Bluetooth, Wi-Fi and eduroam, the internal screen's scaling, the touchpad, audio, the webcam, and the firmware's Secure Boot setup mode.
