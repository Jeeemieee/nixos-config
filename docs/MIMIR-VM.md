# Mimir VM

A minimal, persistent NixOS KDE Plasma trial for `jeeemieee`. This is **not** an installer or a configuration for the physical laptop. ParaView, solver environments, backup/sync services, and other applications are deferred until the desktop works well.

## What is included

- Stock KDE Plasma with SDDM login, NetworkManager, PipeWire, and Git
- A normal `jeeemieee` account with password-authenticated `sudo`; root login is locked
- 4 virtual CPUs, 8 GiB RAM, and a dynamically allocated 24 GiB ext4 guest disk
- QEMU user-mode networking with no incoming port forwards and no SSH server
- Home Manager integration, managing the VM display mode without inherited dotfiles or themes
- A guest-only age identity and root-only encrypted test secret; see [SECRETS.md](SECRETS.md)
- VS Code, configured entirely from Nix; see [VS Code](#vs-code)
- A declared Git identity (`Jeeemieee`, GitHub noreply email, default branch `main`) from `homeManager.git`

There are no physical disk mappings, GPU passthrough, home/project shares, friend-specific credentials, Disko layouts, ZFS, or impermanence. The guest mounts the Ubuntu host's `/nix/store` read-only and uses its own persistent writable overlay. Do not use this trial to run untrusted code: it has network access, and it can read the host store. It is not a portable, standalone VM image.

This uses the generated QEMU launcher directly, **not virt-manager/libvirt**. It will not appear in virt-manager. Building does not boot the VM, install NixOS onto Ubuntu, or modify Ubuntu's bootloader.

## Build on Ubuntu

Nix and working KVM access are required; both were already available on this machine. Keep enough host disk space for Nix downloads/build outputs and the growing guest disk. A 24 GiB virtual disk limit does not include the host Nix store.

From this checkout:

```bash
cd ~/repos/nixos-config
nix --extra-experimental-features 'nix-command flakes' build --no-write-lock-file --out-link result 'path:'"$PWD"'#nixosConfigurations.mimir-vm.config.system.build.vm'
```

`result` is a build-output symlink, not the guest disk. Keep it while using the VM so the required host store paths remain reachable by Nix garbage collection. The explicit `path:` reference includes new, unstaged configuration files without requiring `git add`. Do not put private keys or other secrets in this repository: a path flake copies its source into the Nix store.

The existing public dependency revisions are retained. The friend's private `futura-secrets` input and its otherwise-unused dependency were removed. Your private `nixos-secrets` repository is now a pinned non-flake input; fetching an uncached revision requires GitHub authentication on Ubuntu. This command does not update the lockfile or pass GitHub credentials into the guest.

## Launch and log in

```bash
mkdir -p "$HOME/.local/state/mimir-vm"
NIX_DISK_IMAGE="$HOME/.local/state/mimir-vm/root.qcow2" ./result/bin/run-mimir-vm-vm
```

Run as your normal Ubuntu user, **not with sudo**, from the repository directory. Keep the terminal open. The first launch creates the virtual disk; subsequent launches reuse it. Only run one instance against that disk at a time.

At the graphical login screen:

- User: `jeeemieee`
- Initial password: `mimir`

This is an intentionally public, VM-only trial password, not a real credential. In Konsole, run `passwd` immediately to choose your own password. Because users are mutable, the changed password survives subsequent launches. The initial password only applies when the account is first created. Do not reuse this configuration or password for the physical laptop or expose it to remote login.

Use the Plasma application menu to explore the desktop. Internet access is provided through Ubuntu's network connection; the guest does not connect directly to the laptop's Wi-Fi hardware. The US keyboard layout, Amsterdam timezone, and English locale are initial defaults.

## Display resolution and fullscreen

The declared VM mode is **1920×1080 (16:9) at 100% scale**, matching both external monitors. The laptop panel is 1920×1200, so fullscreen on that panel can leave unused vertical space. This is one virtual display, not a mirror of the host's entire multi-monitor layout.

Move the QEMU window to the desired monitor and use **View → Fullscreen** (`Ctrl+Alt+F`). Window decorations take extra space in windowed mode; QEMU's zoom-to-fit scales the picture but does not change the guest's actual resolution. `Ctrl+Alt+G` releases a grabbed keyboard/mouse.

The resolution is declared once in `virtualisation.resolution` and used both for the virtio GPU's EDID (`xres`/`yres`) and the Home Manager `mimir-vm-display` user service. After Plasma starts, that service applies the mode and scale to the VM's `Virtual-1` output, overriding a previously saved low-resolution setting. It runs once per graphical session; a manual change during a session is not continuously policed, but the declared mode is restored at the next login. Keep intended changes in the Nix configuration rather than relying on GUI settings. There is no automatic resize-to-window integration.

After rebuilding, **shut down and relaunch QEMU** with the same disk path, then log into KDE. Rebooting only inside the running guest does not recreate the virtual GPU or select a new launcher build. Do not delete the VM disk or reset unrelated KDE settings.

If the mode is still wrong, these read-only commands inside Konsole show the actual state:

```bash
kscreen-doctor -o
systemctl --user status mimir-vm-display.service --no-pager
```

The service should be `active (exited)` after a successful login. Its declared target is VM-specific; it is not a monitor policy for the physical laptop or server.

## VS Code

`modules/dev/editors/vscode.nix` defines the reusable `homeManager.vscode` module; the VM imports it for `jeeemieee`. Start it from the application menu or with `code`.

Everything it manages is declared in that file and **read-only** at runtime:

- `settings.json` is a symlink into the Nix store. Telemetry is off, the AI/Copilot UI is disabled, and the theme is Default Dark Modern. Changes made in the settings UI cannot be saved
- Extensions come only from Nix and are fixed: Nix (`nix-ide`, with `nil` supplied as its language server), Python (with Pylance and debugpy), Jupyter (with its four companion extensions), and C/C++ (`cpptools`). The extensions directory is read-only, so installing from the Marketplace fails by design
- VS Code and its extensions never update themselves; versions change only when `flake.lock` does

To change anything, edit `vscode.nix`, rebuild, and relaunch the VM. Pylance, `cpptools`, and VS Code itself are unfree; the repository already permits unfree packages. Home Manager uses the system package set (`useGlobalPkgs`) and installs user packages through the system closure (`useUserPackages`), so `code` comes from `/etc/profiles/per-user/jeeemieee` rather than a mutable user profile. Both are set for every host in `modules/flake/host-machines.nix`.

Not covered: compilers, Python interpreters/kernels, and CMake tooling come from per-project or later declarative environments. Runtime state, such as the welcome page's progress or window layout, is not configuration and is not declared.

## Shut down and restart

Use **Application menu → Shut Down**, or run `sudo poweroff` inside the guest. Wait for the QEMU process/window to exit before launching again. Avoid closing the QEMU window or killing the process while the guest is writing data.

Home files, settings, and the changed login password persist in `~/.local/state/mimir-vm/root.qcow2`. This is an experiment, not a backup destination: keep irreplaceable work elsewhere until the migration/backup plan is ready.

## Make changes later

1. Shut down the VM completely
2. Edit the Nix configuration in this Ubuntu checkout
3. Run the validation and build commands below/on this page
4. Launch again with the **same** `NIX_DISK_IMAGE` path

The launcher directly boots the newly built kernel/system while retaining guest data. Do **not** use the inherited `just rebuild`, bootstrap, Disko, or deploy-rs recipes. Do not run `nixos-rebuild switch` on Ubuntu. For this launcher-based trial, rebuild on Ubuntu rather than switching system configurations inside the guest; it boots the system selected by the launcher, not an in-guest bootloader generation.

Relevant files:

- `modules/hosts/mimir-vm/default.nix`: desktop selection, account, locale, and virtual hardware
- `modules/desktop/environment/kde/default.nix`: reusable stock KDE desktop module
- `modules/flake/host-machines.nix`: personal host allowlist
- `modules/flake/checks.nix`: configuration safety and encrypted-manifest checks
- `modules/dev/editors/vscode.nix`: reusable declarative VS Code
- `modules/dev/git/identity.nix`: reusable declared Git identity
- `modules/core/security/personal-secrets.nix`: shared key provisioning and opt-in test-secret modules

Other selected applications can be added later without replacing this VM's data disk. The physical `mimir` host will need a separate hardware/boot/storage configuration and its own acceptance tests.

## Shared configuration architecture

This keeps the original **flakes + flake-parts + import-tree** (dendritic) architecture; the repository does not use Snowfall. `flake.nix` discovers module files, and `host-machines.nix` assembles the explicitly selected personal hosts. New files under `modules/` must be flake-parts modules, not bare NixOS modules accidentally fed to the import tree.

`flake.modules.nixos.desktop-kde` defines Plasma/SDDM once and imports the existing shared `desktop` audio module. The VM imports `desktop-kde`; a future physical `mimir` can import exactly the same desktop. Applications added later should likewise be named shared NixOS or Home Manager modules, selected by each host/user rather than copied into every host. A server need not inherit workstation applications.

The account's VM-only initial password, virtual hardware, and temporary host defaults deliberately stay in `host-mimir-vm`. Home Manager currently manages the VM display service, VS Code and the Git identity; further application and dotfile modules will be added as needed. Do not reuse the VM host wholesale for the physical laptop: create a separate host, reuse the desired shared modules, and add it to the personal host allowlist.

One SSH key per machine, generated on that machine; only public keys are declared; no SSH keys in sops. The VM has no GitHub key.

The inherited `core` group is intentionally not imported by this VM because it combines friend-specific secrets, security, boot, and storage assumptions. Its files remain unchanged as references, not as a promise that those legacy hosts can still be built without their original private metadata. VM targets are excluded from deploy-rs.

## Validate

```bash
nix --extra-experimental-features 'nix-command flakes' flake check --no-write-lock-file 'path:'"$PWD"
```

Three checks cover this VM. `mimir-vm-config` asserts the policies that matter: the personal-only host list, no auto-login, a single normal account, locked root, password-authenticated sudo, disabled SSH, an enabled firewall, no port forwards, restricted directory sharing, declarative Home Manager packages, a read-only VS Code configuration, a GitHub noreply Git email, and the secrets key's location and permissions. `mimir-vm-secrets` validates the encrypted test secret and the enrollment-only mode without a decryption key. `mimir-vm-system` builds the whole system closure. They complement, rather than replace, a real boot and desktop test.

After booting, check that login, Konsole, networking, sudo, shutdown, and restart work, and that a test file in your home survives restart. Check display scaling, keyboard behavior, and basic desktop responsiveness. Virtual graphics do not validate the laptop's NVIDIA hybrid graphics, suspend, docking, or Secure Boot.

## Starting over without deleting the old trial

Shut down first, then use a **different** `NIX_DISK_IMAGE` filename (for example `root-fresh.qcow2`). This creates a fresh guest with the initial password and preserves the old disk. Its new age identity is not enrolled in the pinned test file, so `sops-install-secrets.service` will fail on that disk until it is enrolled (or `hostSpec.hasSecrets` is set to `false`); see [SECRETS.md](SECRETS.md). Do not delete a disk unless you are sure no needed data remains.
