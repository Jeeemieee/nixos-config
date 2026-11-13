# Installation

A physical host is installed from another Linux system with Nix (the laptop's Ubuntu), through a virtual machine, the installer, that can see only the target disk. The system is built on the host; the installer has no network and receives no credentials. `modules/install/installer.nix` defines the installer and the `install` tool; the same steps serve a rehearsal on a disk image file and the real disk.

Commands on the host are run in the nixos-config checkout:

```bash
alias install-nixos="nix --extra-experimental-features 'nix-command flakes' run path:$PWD#install --"
```

## Steps

1. **Start the installer.**
   - Real disk: `install-nixos start mimir --disk /dev/disk/by-id/<disk>`. The tool shows the disk's size, partitions, model and serial number, and starts only after the serial number is typed. It refuses anything that is not a whole, writable disk of at least 96 GiB with a serial number, and any disk with a mounted partition or active swap, which includes the disk the running system is on. Without write access to the device it prints the `setfacl` command that grants it for the session
   - Rehearsal: `install-nixos start mimir --image ~/.local/state/nixos-install/mimir-rehearsal.raw`. The file is created as a sparse 2000 GiB image, the size of the laptop's disk, so that the layout's reservation for `/home` fits; it only takes the space that is written; an existing image with data is only overwritten after typing `erase`

   The installer's console is the terminal. It logs in as root and lists its commands.
2. **Format, in the installer:** `install-format`. It erases the target, asks for the disk passphrase twice, creates the layout of [DISK.md](DISK.md), mounts it at `/mnt`, generates the machine's age key at `/var/lib/sops-nix/key.txt` on the target, and prints the public key. The key never leaves the target disk. The formatting tool prints every command it runs; messages such as `cannot import 'rpool': no such pool available` are its probes for an existing pool.
3. **Enroll the key, on the host**, in the nixos-secrets checkout: add the public key under `keys` in `.sops.yaml` and to the rules of `secrets/shared.yaml` and `secrets/<host>.yaml`, then re-encrypt, publish, and update the pin:

   ```bash
   cd ~/repos/nixos-config && nix --extra-experimental-features 'nix-command flakes' develop "path:$PWD"
   cd ~/repos/nixos-secrets
   sops updatekeys secrets/shared.yaml
   sops updatekeys secrets/mimir.yaml
   git add -A && git commit -m "Enroll mimir" && git push
   exit
   cd ~/repos/nixos-config && nix --extra-experimental-features 'nix-command flakes' flake update nixos-secrets --flake "path:$PWD"
   ```
4. **Build, on the host:** `install-nixos system mimir`. It builds the host's system and hands its path to the running installer.
5. **Install, in the installer:** `install-system`. It first decrypts every secret of the built system with the machine's key and refuses to install if one fails, because the login password is decrypted at the first boot and the account would have no password. Then it copies the system from the host's store to the target and installs the boot files. In the dry run this took under three minutes for 33 GiB, which compress to 17 GiB on disk.
6. **Finish, in the installer:** `install-finish` unmounts the target, exports the pool, closes the encrypted container and powers the installer off.
7. **Boot the disk.**
   - Rehearsal: `install-nixos boot mimir --image <file>` starts a machine with Secure Boot firmware in setup mode, the image as a USB disk (as the laptop's disk in its enclosure; `INSTALL_DISK_BUS=nvme` attaches it as an NVMe disk), and no network, so that the laptop's single-use Tailscale key is not spent (`INSTALL_NETWORK=1` connects it). Its firmware variables are kept in `~/.local/state/nixos-install/mimir/rehearsal-efi-vars.fd`; delete that file to start from setup mode again
   - Laptop: put Secure Boot in setup mode in the firmware menu (see [SECURE-BOOT.md](SECURE-BOOT.md)), then choose the disk in the firmware's boot menu

   The first boot asks for the disk passphrase, creates the account with the password from nixos-secrets, generates the Secure Boot keys and prepares their enrollment; `bootctl status` shows `Secure Boot: disabled (setup)`. After a reboot the keys are enrolled: `sudo sbctl status` shows `Setup Mode: Disabled`, `Secure Boot: Enabled`, `Vendor Keys: microsoft`.

If the installer was closed between the steps, start it again without formatting: answer the confirmation, then run `install-mount` (it asks for the disk passphrase) and continue. `install start` with `--image` recreates the image, so for an image restart the installer only before `install-format`.

## After a rehearsal

Remove the rehearsal machine's recipient from `.sops.yaml`, run `sops updatekeys` on both files, publish, update the pin, and delete the image and the firmware variables. The rehearsal key only existed inside the encrypted image.

## What was verified

A dry run on 2026-11-13 went through all steps with a disk image, a throwaway passphrase and stand-in secrets encrypted for the throwaway machine key: the installer saw one disk and no network; `install-system` refused the system built with the real secrets (`CANNOT DECRYPT` for each) and installed the one whose secrets it could decrypt; the installed system asked for the passphrase, reached the login screen, accepted the password from the secrets in the graphical login, on a text console and for `sudo`; Home Manager, the secrets, the Wi-Fi profiles and the snapshot timer were active, and only `tailscaled-autoconnect` had failed (no network); the home folders were lowercase; a deleted file was restored from a sanoid snapshot; after the reboot Secure Boot was enabled with Microsoft's keys, and `sbctl verify` reported everything signed except the kernel file, as expected.

The `install-disk-validation` check runs the disk validation against recorded cases, and `install-tool` builds the tool and the installer.

Not verified: a real disk (the `--disk` path beyond its validation, and the device permissions), the laptop's firmware and its setup mode, booting next to Ubuntu, and the hardware listed in [MIMIR.md](MIMIR.md). The dry run booted the image as an NVMe disk; booting it as a USB disk, which the laptop host supports through the `usb_storage` and `uas` drivers in its first boot stage, is part of the rehearsal.
