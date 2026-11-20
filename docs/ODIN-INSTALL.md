# Installing Odin: NixOS first, Windows second

This is the installation order for Odin's 1 TB system disk. NixOS deliberately erases the whole disk first and leaves a real 200 GiB unallocated gap. Windows 11 is then installed only into that gap. There is no Windows-preservation mode and no fallback that formats around an existing Windows installation.

The hardware-independent configuration may be prepared now, but do not install until the real facts, private files and game-storage plan have been reviewed. Disconnect the game disk and every backup disk throughout the operating-system installation.

## What is tested, and what is not

Automated checks prove the declarative partition geometry, encrypted ZFS recipe, installer refusals, generated-secret system build, gaming settings, save timer, backup rules and two-interface SSH policy. They do not test Odin's real disk, firmware, AMD GPU, monitors, audio, network devices, controllers, anti-cheat software or the Windows installer.

Stop instead of improvising when a disk identity, partition size, firmware label or expected boot entry differs from this page.

## Part A. Prepare facts and private files

### A1. Inspect the machine

Boot a current NixOS installer or another Linux system on Odin with the system disk and network hardware present. Keep Secure Boot off because the NixOS installer is not signed.

Record the physical network names:

```bash
ip -br link
```

Ignore `lo` and temporary virtual interfaces. Record the stable system-disk links and resolve the selected one:

```bash
ls -l /dev/disk/by-id/
readlink -f /dev/disk/by-id/<selected-system-disk>
lsblk -dn -o NAME,SIZE,MODEL,SERIAL,TRAN /dev/disk/by-id/<selected-system-disk>
```

The by-id path must be the path visible on the Linux machine that will run `config install start`. An enclosure can give the disk a different path from its internal connection; the installed system uses partition labels afterwards.

Generate and record a new eight-hex-digit ZFS host ID:

```bash
od -An -N4 -tx4 /dev/urandom | tr -d ' \n'
```

### A2. Declare the facts

In `modules/hosts/odin/default.nix`, add the real values inside `host-odin`, beside the host name:

```nix
hostSpec.odin = {
  systemDiskById = "/dev/disk/by-id/<exact-install-target>";
  hostId = "<eight-hex-digits>";
  networkDevices = [
    "<ethernet-interface>"
    "<wifi-interface-if-present>"
  ];
};
```

Do not change the declared 2 GiB EFI size, 200 GiB Windows gap, 32 GiB swap or ZFS capacities without a separate storage review.

### A3. Prepare the private input

In `nixos-secrets`:

1. Create `ssh/odin_authorized_keys` as a plain file containing the OpenSSH public key whose private half remains in Bitwarden. Do not copy the private key.
2. Add a `.sops.yaml` creation rule for `secrets/odin.yaml`, initially using the admin and recovery recipients.
3. Create `secrets/odin.yaml` with Odin's own values for `tailscale_authkey`, `restic_env` and `restic_password`. Create a separate append-only rest-server login and restic key; do not reuse Mimir's credentials.
4. Add an `odin` host to the private `ssh/config`, using its Tailscale DNS name and user `jeeemieee`. Do not put its private address in the public repository.
5. Commit and publish the private repository, then update the `nixos-secrets` pin in this repository.

`secrets/shared.yaml` already supplies `wifi_env` and `user_password_hash`. Know that login password before continuing: root has no password.

Run the focused checks and commit the prepared public configuration before using `config install`; the guarded install workflow builds from the committed configuration.

## Part B. Install NixOS into the whole disk

Use the same isolated installer described in [INSTALL.md](INSTALL.md). The examples assume the checkout is `~/repos/nixos-config`:

```bash
alias config="nix --extra-experimental-features 'nix-command flakes' run path:$HOME/repos/nixos-config#config --"
cd ~/repos/nixos-config
```

### B1. Disconnect other disks

Power off Odin. Disconnect the game disk and every backup or removable storage device. Connect only the 1 TB system disk to the Linux installation host, or boot the reviewed Linux environment that will run the installer.

Recheck its model, serial number and exact configured path:

```bash
lsblk -dn -o NAME,SIZE,MODEL,SERIAL,TRAN /dev/disk/by-id/<exact-install-target>
```

### B2. Start the isolated installer

If needed, grant the current account temporary write access:

```bash
sudo setfacl -m u:$USER:rw /dev/disk/by-id/<exact-install-target>
```

Start the installer:

```bash
config install start odin --disk /dev/disk/by-id/<exact-install-target>
```

It refuses before touching the disk unless all three facts, `ssh/odin_authorized_keys` and `secrets/odin.yaml` are present. It also refuses a partition, mounted or swap-active disk, a read-only disk, a disk without a serial number, or a disk smaller than the installer minimum.

Read the displayed model, size and serial number. Type the serial number only if they identify the intended empty target. The next step erases it completely.

### B3. Format and obtain the machine recipient

In the installer console:

```bash
install-format
```

Choose a strong disk passphrase and store it in Bitwarden. The command creates:

1. a 2 GiB EFI partition
2. a 200 GiB unallocated gap for Windows
3. 32 GiB random-key encrypted swap
4. a LUKS container with the shared ZFS datasets in all remaining space

It then prints Odin's new public age recipient. Copy only that public `age1...` value.

### B4. Enrol Odin's machine key

On the host, in `nixos-secrets`:

1. Add the recipient under `keys:` in `.sops.yaml` with an `odin` anchor.
2. Add `*odin` to the creation rules for `secrets/shared.yaml` and `secrets/odin.yaml`.
3. Re-encrypt both files:

```bash
cd ~/repos/nixos-config
nix --extra-experimental-features 'nix-command flakes' develop "path:$PWD"
cd ~/repos/nixos-secrets
sops updatekeys secrets/shared.yaml
sops updatekeys secrets/odin.yaml
```

4. Commit and push `nixos-secrets`.
5. Update and commit the `nixos-secrets` pin in `nixos-config`.

No private machine key leaves the encrypted target disk.

### B5. Build and install

On the host:

```bash
cd ~/repos/nixos-config
config install system odin
```

In the installer console:

```bash
install-system
```

It must print `can decrypt` for `wifi_env`, `user_password_hash`, `tailscale_authkey`, `restic_env` and `restic_password`. Any `CANNOT DECRYPT` line is a stop: the command installs nothing until the recipient and pin are corrected.

When installation finishes:

```bash
install-finish
```

Do not resize or format the disk again. Put it in Odin if it was installed through another machine.

## Part C. Install Windows 11 into the gap

### C1. Boot the Windows installer

Keep the game disk and backup disks disconnected. Boot current Windows 11 installation media in UEFI mode with Secure Boot still off. At the disk-selection screen choose **Custom: Install Windows only**.

The target contains an existing 2 GiB EFI partition, NixOS swap, an unknown/encrypted NixOS partition and one unallocated region of about 200 GiB immediately after the EFI partition. Select **only that unallocated region** and press **Next**. Let Windows create its Microsoft reserved, Windows and recovery partitions inside the gap and use the existing EFI system partition.

Do not delete, format or resize any existing partition. If Windows proposes using space outside the approximately 200 GiB unallocated region, stop and return to Linux to inspect the GPT.

### C2. Use a local account and minimum telemetry

Keep Ethernet disconnected and do not join Wi-Fi during out-of-box setup. Choose **I don't have internet** and **Continue with limited setup**, when offered, then create the local account. If those buttons are absent, press `Shift+F10`, run `OOBE\BYPASSNRO`, and after the restart choose the offline route. Microsoft changes OOBE between media releases; if that command is refused too, stop and obtain a reviewed local-account method for that exact installer instead of entering a Microsoft account merely to continue.

When the privacy questions appear:

- leave only required diagnostic data enabled; turn optional diagnostic data off
- turn the advertising ID off
- turn tailored experiences and similar personalised advertising suggestions off

After reaching the desktop, check **Settings → Privacy & security → Diagnostics & feedback** and keep optional diagnostic data off. Check **Settings → Privacy & security → General** and keep the advertising ID off. Turn Copilot off in the current Windows location, commonly **Settings → Personalisation → Taskbar** or **Settings → System → Copilot**. Windows labels move between releases; verify that no Copilot taskbar or startup integration remains enabled.

Do not install Bitwarden or Tailscale on Windows and do not store personal files there.

### C3. Finish Windows preparation

Install Windows updates and the AMD and network drivers. Confirm activation, UEFI mode and TPM 2.0. In an elevated terminal disable hibernation and Fast Startup:

```powershell
powercfg /h off
```

Restart Windows twice. Confirm it still boots and that Disk Management shows the NixOS partitions unchanged. Windows is not backed up.

## Part D. Enrol Secure Boot and restore NixOS as default

Windows normally makes **Windows Boot Manager** first in the firmware boot order. This is expected once.

1. Enter the firmware setup. Keep UEFI mode and TPM enabled, disable CSM, and put Secure Boot into setup mode by deleting the enrolled keys. Do not restore factory keys at this point.
2. Use the firmware's one-time boot menu to choose **Linux Boot Manager**.
3. Enter the NixOS disk passphrase and log in. Check:

   ```bash
   bootctl status | head -n 12
   ```

   Expected on this first boot: `Secure Boot: disabled (setup)`.
4. Reboot and choose **Linux Boot Manager** once more if the firmware still starts Windows. The prepared keys are enrolled on this boot, including Microsoft's keys.
5. Check:

   ```bash
   sudo sbctl status
   sudo sbctl verify
   bootctl status
   ```

   Expected: setup mode disabled, Secure Boot enabled, vendor keys include `microsoft`, and only the documented kernel files are reported unsigned by `sbctl verify`.
6. In the firmware boot-order page, put **Linux Boot Manager** before **Windows Boot Manager**. This is the one permanent boot-order repair after the Windows installation.
7. From the systemd-boot menu, boot Windows once and confirm Microsoft's boot manager still works under Secure Boot. Return to NixOS and use the Plasma **Reboot into Windows** entry; it should select Windows for one boot and return to NixOS as the default afterwards.

If either system is refused, switch Secure Boot off to recover. Restoring factory keys makes Windows bootable but removes Odin's keys; put the firmware in setup mode and repeat the NixOS enrolment afterwards. See [SECURE-BOOT.md](SECURE-BOOT.md).

## Part E. First NixOS checks

### E1. Services and graphics

```bash
systemctl status home-manager-jeeemieee
systemctl is-active sops-install-secrets.service
vulkaninfo --summary
glxinfo -B
tailscale status
```

If the one-use Tailscale key expired, enrol interactively with `sudo tailscale up`. Test a native game and a Proton game, then Gamescope, GameMode and MangoHud. Test each controller in Steam. Record the real results in [ODIN.md](ODIN.md); virtual-machine results are not hardware evidence.

### E2. Saves and backup

Run the save export and inspect actual files:

```bash
systemctl --user start ludusavi-backup.service
systemctl --user status ludusavi-backup.service
find ~/game-saves/ludusavi -type f | head
```

Start the first backup, then restore one exported file into an empty temporary folder and compare it byte for byte:

```bash
sudo systemctl start restic-backups-home.service
systemctl status restic-backups-home.service
sudo restic-home snapshots --host odin --path /home
```

Keep valuable simulation results, documents, screenshots, mods and custom configuration under `/home`, but outside `~/scratch` and the excluded game-library paths. The game libraries, `~/scratch` and Windows are not backed up.

### E3. Remote access

From Mimir, with Bitwarden unlocked and its SSH agent enabled:

```bash
ssh odin
```

It must work through Odin's Tailscale name. From an ordinary LAN path that does not use `tailscale0`, TCP 22 must be unreachable. Password, root and any user other than `jeeemieee` must remain refused.

Reconnect the separate game disk only after the operating systems, Secure Boot, backup restore and SSH checks pass. Its partitioning and the final game list are separate work and are not declared by this implementation.
