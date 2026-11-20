# Secure Boot

`modules/boot/secure-boot.nix` defines `nixos.secure-boot`, using [lanzaboote](https://github.com/nix-community/lanzaboote) 1.2.0. Physical hosts import it next to `nixos.boot`; `mimir` and `odin` do.

## How it works

- lanzaboote installs the boot files and signs them with keys in `/var/lib/sbctl`, on the machine's encrypted disk; systemd-boot remains the boot menu
- On the first boot the machine generates its own keys (`generate-sb-keys.service`), signs the boot files and prepares the enrollment (`prepare-sb-auto-enroll.service`). At the next boot systemd-boot enrolls the keys in the firmware, and Secure Boot is enforced from then on
- Microsoft's keys are enrolled as well: Ubuntu on Mimir, Windows on Odin, and firmware components signed by Microsoft remain bootable
- The firmware starts the boot menu and one image per system generation; these are signed. The kernel and initrd are not signed themselves: the signed image contains their hashes and refuses to start them when they differ

Enrollment needs the firmware's Secure Boot in **setup mode** once (no platform key enrolled), set in the firmware menu before the first boot of the installed system. In any other mode the keys are generated and the files signed, but nothing is enrolled. On Odin, do this only after Windows has been installed into the reserved gap, so the final enrolment and boot-order repair cover both systems; see [ODIN-INSTALL.md](ODIN-INSTALL.md).

## Inspect

```bash
sudo sbctl status   # Setup Mode: Disabled, Secure Boot: Enabled, Vendor Keys: microsoft
sudo sbctl verify   # every file signed, except /boot/EFI/nixos/kernel-*.efi, which is expected
bootctl status      # Secure Boot: enabled (user)
```

## Recovery

- The firmware menu can restore the factory keys or switch Secure Boot off; with Secure Boot off the system still boots. Secure Boot therefore only helps against someone at the keyboard while the firmware menu has a password of its own
- The NixOS installer is not signed: switch Secure Boot off in the firmware to boot it
- On Odin, restoring factory keys makes Windows bootable but removes Odin's keys. Put the firmware back in setup mode, boot **Linux Boot Manager** from the one-time menu and repeat the NixOS enrolment. Keep **Linux Boot Manager** before **Windows Boot Manager** in the permanent firmware order; the desktop's one-shot Windows action does not change that default
- If `/var/lib/sbctl` is lost, new keys are generated at the next boot, and the firmware has to be put in setup mode again to enroll them

## Validation

The `secure-boot` check (`nix flake check`) boots the module in a virtual machine whose firmware supports Secure Boot and starts in setup mode, and checks that

1. on the first boot Secure Boot is off and the machine generates its keys
2. after a reboot the firmware enforces Secure Boot with these keys, and Microsoft's keys are enrolled
3. everything the firmware starts is signed, and only kernel files are reported as unsigned
4. a tampered kernel is refused at boot (`Kernel hash does not match`)
5. the keys are not generated again

The check reuses lanzaboote's own test harness (`nix/tests/lanzaboote/common` in its source), which is internal to lanzaboote and tied to the pinned version. Two adjustments make it work on NixOS 26.05: the test declares `image.repart.enable`, which only newer NixOS has, and switches on Secure Boot support in the virtual firmware.

Not covered by the check: either physical firmware and its setup mode, Secure Boot together with encrypted ZFS, dual boot with Ubuntu or Windows, Windows' `auto-windows` discovery, and the real boot order. Those are tested in the relevant install rehearsal and on the physical machine.
