# Installing mimir: the order of the day

The laptop's installation on the 2 TB disk in its USB enclosure, next to Ubuntu, in the order it is done. [INSTALL.md](INSTALL.md) explains the steps; this page only lists them with their commands. Ubuntu's disk is not written at any step.

- **Part A** is done on Ubuntu, about 45 minutes. Nothing is changed on the laptop's firmware yet.
- **Part B** is the firmware and the first two boots, about 15 minutes. Read it on a phone or on paper: the laptop restarts.
- **Part C** is the first hour on NixOS.

If a step of part A fails, nothing is lost: the disk is empty, and the step or the whole part can be repeated.

## What was tested, and what was not

- **Tested**, twice, with a disk image and stand-in secrets: all of part A's installer steps, the passphrase prompt, the login and the desktop ([INSTALL.md](INSTALL.md), "What was verified").
- **Not tested**, because they need the real disk, the real secrets or the laptop's firmware: the `--disk` path beyond its validation, re-encrypting the real secrets for the laptop's key, how long the copy takes on the USB disk, every step of part B on the Dell firmware, and part C's copy from the Ubuntu disk. The firmware menu's names in part B are Dell's as documented for this model family; they may differ slightly.

## Before you start

- You know the **login password** whose hash is in `secrets/shared.yaml` (`user_password_hash`). It is the only way into the new system: root has no password. If you are not sure of it, set a new one in step A3.
- You have a **disk passphrase** in mind and stored in Bitwarden. It is typed at every boot.
- The laptop is on mains power and on the home Wi-Fi.
- Both repositories are clean: `git status` shows nothing in `~/repos/nixos-config` and in `~/repos/nixos-secrets`.

In **every** terminal of part A, first:

```bash
alias config="nix --extra-experimental-features 'nix-command flakes' run path:$HOME/repos/nixos-config#config --"
```

## Part A. On Ubuntu

Two terminals: the **installer terminal** and the **host terminal**.

### A1. Start the installer (installer terminal)

The disk, as Ubuntu names it: `usb-Samsung_SSD_990_EVO_Plus_012345678923-0:0` (1,8T; the serial number is the enclosure's). Check that it is the one that is plugged in:

```bash
lsblk -dn -o NAME,SIZE,MODEL,SERIAL,TRAN /dev/disk/by-id/usb-Samsung_SSD_990_EVO_Plus_012345678923-0:0
```

Expected: one line with `1,8T`, `SSD 990 EVO Plus`, `012345678923`, `usb`.

Give your account write access to that disk for this session:

```bash
sudo setfacl -m u:$USER:rw /dev/disk/by-id/usb-Samsung_SSD_990_EVO_Plus_012345678923-0:0
```

```bash
cd ~/repos/nixos-config
```

```bash
config install start mimir --disk /dev/disk/by-id/usb-Samsung_SSD_990_EVO_Plus_012345678923-0:0
```

It shows the disk's size, model and serial number and asks for the serial number: type `012345678923`. The installer starts in this terminal, logs in as root and lists its commands.

### A2. Format (installer terminal)

```bash
install-format
```

It asks for the disk passphrase twice, creates the layout, and ends with **this machine's public key**, a line that starts with `age1`. Copy that key.

### A3. Enrol the laptop's key (host terminal)

1. In `~/repos/nixos-secrets/.sops.yaml`:
   - under `keys:`, below the line of `&mimir-vm`, add a line `  - &mimir <the key from A2>`;
   - in the rule of `secrets/shared.yaml` and in the rule of `secrets/mimir.yaml`, add a line `          - *mimir` below `- *recovery`.
2. Open the tools:

```bash
cd ~/repos/nixos-config
```

```bash
nix --extra-experimental-features 'nix-command flakes' develop "path:$PWD"
```

```bash
cd ~/repos/nixos-secrets
```

3. Re-encrypt both files for the new key. Each asks for the admin key's passphrase (Bitwarden) and then `y`:

```bash
sops updatekeys secrets/shared.yaml
```

```bash
sops updatekeys secrets/mimir.yaml
```

4. Only if you want a new login password: `mkpasswd -m sha-512` prints a hash for the password you type; `sops secrets/shared.yaml` opens the file, where the hash replaces the value of `user_password_hash`.
5. Leave the tools and commit; the commit asks for `yes` because `.sops.yaml` is protected:

```bash
exit
```

```bash
alias config="nix --extra-experimental-features 'nix-command flakes' run path:$HOME/repos/nixos-config#config --"
```

```bash
cd ~/repos/nixos-secrets
```

```bash
config commit "Enrol mimir"
```

```bash
git push
```

6. Take the new secrets into the configuration; the commit asks for `yes` because `flake.lock` is protected, and runs the checks that depend on the secrets (some minutes):

```bash
cd ~/repos/nixos-config
```

```bash
config update secrets
```

```bash
config commit "Pin nixos-secrets with mimir enrolled"
```

```bash
git push
```

### A4. Build the system (host terminal)

```bash
config install system mimir
```

Expected at the end: `Built: /nix/store/…-nixos-system-mimir-…` and `Now run install-system in the installer.`

### A5. Install (installer terminal)

```bash
install-system
```

Expected first: one line `can decrypt: <name>` for each of `wifi_env`, `user_password_hash`, `tailscale_authkey`, `restic_env`, `restic_password`. A line `CANNOT DECRYPT` means step A3 is not complete; nothing is installed then. After that it copies the system (33.6 GiB; two and a half minutes into an image, longer on the USB disk) and ends with `Installed. Run install-finish to unmount the target and power off.`

### A6. Finish (installer terminal)

```bash
install-finish
```

The installer powers off and the terminal is yours again. Part A is done; Ubuntu can be shut down.

## Part B. The firmware and the first two boots

The new system's boot files are not signed yet. The firmware therefore has to be in **setup mode** (no Secure Boot keys) for the first boot; the system then enrols its own keys and Microsoft's, and Secure Boot is on again from the third start. Ubuntu keeps starting throughout.

1. Restart the laptop and press **F2** at the Dell logo: the firmware menu.
2. **Boot Configuration**, **Secure Boot**: under **Expert Key Management**, switch on **Enable Custom Mode**, then **Delete All Keys**, and confirm. Apply the changes and leave the menu.
3. At the Dell logo press **F12**: the one-time boot menu. Choose the USB disk (it is listed as a UEFI device, by the name of the disk or as `Linux Boot Manager`). If it is not listed: F2, **Boot Configuration**, and allow booting from USB devices.
4. The boot menu of NixOS appears, then `Please enter passphrase for disk`: type the disk passphrase. It may be typed at leisure.
5. Log in as `jeeemieee` with the login password.
6. Open Konsole:

```bash
systemctl status home-manager-jeeemieee
```

Expected: `active (exited)`.

```bash
bootctl status | head -n 12
```

Expected among the lines: `Secure Boot: disabled (setup)`.

7. Restart from the menu, press **F12** again and choose the same disk. On this start the keys are enrolled; the laptop may restart once more by itself. Then, after the login:

```bash
sudo sbctl status
```

Expected: `Setup Mode: Disabled`, `Secure Boot: Enabled`, `Vendor Keys: microsoft`.

Until the firmware has an entry of its own for the disk, NixOS is started with **F12**; without it the laptop starts Ubuntu, as before.

**If something goes wrong in part B:** start the laptop without F12: Ubuntu starts. If the firmware refuses to start Ubuntu after step 2, switch Secure Boot off in the same firmware menu, or choose **Restore Factory Keys** under Expert Key Management, which undoes step 2.

## Part C. The first hour on NixOS

1. **The network.** The home Wi-Fi connects by itself. Tailscale: `tailscale status` lists your devices; if it says `Logged out`, the stored key has expired: `sudo tailscale up` prints an address to log in with.
2. **Bitwarden:** log in, and tick Settings, "Enable SSH agent".
3. **What is needed from Ubuntu**, read-only from its disk: the two repositories, the admin key for the secrets, and the archive of this migration.

```bash
sudo mkdir -p /mnt/ubuntu
```

```bash
sudo mount -o ro,noload UUID=006b41e5-c321-4698-b56c-74e7fe0b511e /mnt/ubuntu
```

```bash
mkdir -p ~/repos ~/.config/sops/age
```

```bash
cp -a /mnt/ubuntu/home/jeeemieee/repos/nixos-config /mnt/ubuntu/home/jeeemieee/repos/nixos-secrets ~/repos/
```

```bash
cp -a /mnt/ubuntu/home/jeeemieee/.config/sops/age/admin.age ~/.config/sops/age/
```

```bash
cp -a /mnt/ubuntu/home/jeeemieee/nixos-migration-archive ~/
```

```bash
sudo umount /mnt/ubuntu
```

4. **The configuration's own tools** are installed: `config check`, `config commit`, `config switch`. Nothing has to be switched now, since the installed system is the last commit. The first `config check` on this machine builds every check once, the numerical libraries for the graphics card among them: start it when the laptop can run by itself for an hour or more, before the first change.

```bash
cd ~/repos/nixos-config
```

```bash
config check
```

5. **pi:** in `~/repos/nixos-config`, start it with the archive readable and the protected files open, log in once with `/login`, and give it the handoff:

```bash
pi --unlock --allow-ro ~/nixos-migration-archive
```

Say to it: `Read ~/nixos-migration-archive/HANDOFF.md and continue from there.`

What remains after that is in the handoff: the checks that only the laptop can do ([MIMIR.md](MIMIR.md), "Validation"), the first backup and a restore ([BACKUP.md](BACKUP.md)), and the worker tools.
