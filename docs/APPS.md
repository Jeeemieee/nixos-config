# Applications

Desktop applications come from the pinned nixpkgs (`flake.lock`) through shared modules in `modules/apps/`. Each host or user selects modules by importing them; the workstation profile (`modules/profiles/workstation.nix`) imports all of them for both hosts. Versions change only when `flake.lock` does. Nothing here updates itself, and nothing here holds an account or credential: logins, accounts and libraries stay manual state inside the VM.

## Programs

Versions are those of the current `flake.lock` (nixos-26.05).

| Program | Module | nixpkgs attribute | Version | Unfree | Declared | Manual state |
| --- | --- | --- | --- | --- | --- | --- |
| Brave | `nixos.browser` | `brave` | 1.99.55 | no | Package; managed policies in `/etc/brave/policies/managed/`: Rewards, Wallet, Brave VPN, Leo AI (`BraveAIChatEnabled`), P3A, the stats ping, Web Discovery and metrics reporting off; Bitwarden, Zotero Connector and Plasma Integration extensions force-installed and the built-in password manager off; the last session's windows and tabs reopen at every start (`RestoreOnStartup`); Memory Saver unloads tabs that have not been used for a while; Startpage as the search engine; spell checking in British English and Dutch; Safe Browsing at standard protection; bookmark bar and home button shown. A policy fixes its setting: the switch in Brave's settings is greyed out | Profile, sync, bookmarks, the extensions' logins, window names |
| Carlito, Caladea, Liberation | `nixos.fonts` | `carlito`, `caladea`, `liberation_ttf` | 20130920, 20130214, 2.1.5 | no | System fonts; fontconfig maps Calibri, Cambria, Arial, Times New Roman and Courier New to them | None |
| LibreOffice | `homeManager.office` | `libreoffice-qt6-still` | 25.8.5.2 | no | Package | User profile and settings |
| Scribus | `homeManager.office` | `scribus` | 1.7.3 | no | Package | Settings |
| Pympress | `homeManager.office` | `pympress` | 1.8.6 | no | Package | Settings |
| British English and Dutch dictionaries | `homeManager.office` | `hunspellDicts.en_GB-ise`, `hunspellDicts.nl_NL` | 2026.02.25 (en_GB) | no | Hunspell dictionaries for LibreOffice and KDE apps (see [Spell checking](#spell-checking)) | Personal word lists |
| Thunderbird | `homeManager.mail` | `thunderbird` | 159.0 | no | Package; one default profile (`~/.thunderbird/default`) whose `user.js` sets `toolkit.telemetry.enabled`, `datareporting.healthreport.uploadEnabled`, `datareporting.policy.dataSubmissionEnabled` and `app.shield.optoutstudies.enabled` to false | Accounts, mail, calendars, address books |
| Obsidian | `homeManager.notes` | `obsidian` | 1.13.7 | yes | Package | Vaults and their settings (vault setup is Phase 4), Obsidian Sync login |
| Zotero | `homeManager.notes` | `zotero` | 9.0.6 | no | Package | Library, data directory, account and sync |
| GIMP | `homeManager.graphics` | `gimp` | 3.0.8 | no | Package | Settings, plug-ins |
| Inkscape | `homeManager.graphics` | `inkscape` | 1.4.4 | no | Package | Settings, extensions |
| Blender | `homeManager.graphics` | `blender` | 5.1.1 | no | Package | Preferences, add-ons |
| gThumb | `homeManager.graphics` | `gthumb` | 3.12.10 | no | Package | Settings, catalogues |
| ImageMagick | `homeManager.graphics` | `imagemagick` | 7.1.2-34 | no | Package (`magick`) | None |
| ParaView | `homeManager.engineering` | `paraview` | 6.0.1 | no | Package | Settings, state files |
| PrusaSlicer | `homeManager.engineering` | `prusa-slicer` | 2.9.4 | no | Package | Printer, filament and print profiles, Prusa account |
| fstl | `homeManager.engineering` | `fstl` | 0.11.1 | no | Package; a menu entry (`fstl.desktop`, nixpkgs installs none) | None |
| MeshLab | `homeManager.engineering` | `meshlab` | 2025.07 | no | Package | Settings |
| gnuplot | `homeManager.engineering` | `gnuplot` | 6.0.4 | no | Package | None |
| TeX Live (full) | `homeManager.tex` | `texliveFull` | 2025 (r78234) | no | Package; every TeX Live package, including `pdflatex`, `lualatex` and `latexmk` | None |
| Discord | `homeManager.media` | `discord` | 1.0.159 | yes | Package | Login, servers; Discord downloads its own modules into `~/.config/discord` |
| Spotify | `homeManager.media` | `spotify` | 1.2.90.451 | yes | Package | Login, cache |
| VLC | `homeManager.media` | `vlc` | 3.0.24 | no | Package | Settings, playlists |
| ffmpeg | `homeManager.media` | `ffmpeg` | 8.1.3 | no | Package | None |
| Teams | `homeManager.meetings` | `teams-for-linux` | 2.29.0 | no | Package; unofficial client around Teams for the web | Work account login |
| Zoom | `homeManager.meetings` | `zoom-us` | 7.1.5.4332 | yes | Package | Login |
| RustDesk | `homeManager.meetings` | `rustdesk-flutter` | 1.4.5 | no | Package; the Flutter client, since `rustdesk` depends on the unfree `libsciter` | ID, password, trusted devices |
| Bitwarden | `homeManager.passwords` | `bitwarden-desktop` | 2026.8.0 | no | Package | Login, vault, unlock settings |
| Bitwarden CLI | `homeManager.passwords` | `bitwarden-cli` | 2026.4.2 | no | Package (`bw`) | Login, session |
| Vim | `homeManager.cli` | `vim-full` (Home Manager's `programs.vim` default) | 9.2.1252 | no | `programs.vim` with `defaultEditor`, so `EDITOR=vim` | None |
| btop | `homeManager.cli` | `btop` | 1.4.8 | no | `programs.btop` | None |
| tree | `homeManager.cli` | `tree` | 2.3.2 | no | Package | None |
| nmap | `homeManager.cli` | `nmap` | 7.99 | no | Package | None |
| TestDisk and PhotoRec | `homeManager.cli` | `testdisk` | 7.2 | no | Package; disk access needs `sudo` | None |
| smartmontools | `homeManager.cli` | `smartmontools` | 7.5 | no | Package (`smartctl`, needs `sudo`) | None |
| fastfetch | `homeManager.cli` | `fastfetch` | 2.63.1 | no | Package | None |
| tmux | `homeManager.cli` | `tmux` | 3.7b | no | `programs.tmux`, with mouse support and 50 000 lines of history; keeps shells and long runs alive when a terminal closes (`Ctrl+b d` detaches, `tmux attach` returns) | None |
| ncdu | `homeManager.cli` | `ncdu` | 2.9.2 | no | Package; shows what takes space in a folder such as `~/scratch` | None |
| pi (coding agent) | `homeManager.pi` | `pi-coding-agent` from nixos-unstable | 1.5.2 | no | Only as the sandboxed launcher `pi`; version check off, `pi update` points to Nix; instructions, settings and five extensions declared read-only (see [MIMIR-VM.md](MIMIR-VM.md#pi)) | Logins, sessions |
| Raspberry Pi Imager | `homeManager.rpi` | `rpi-imager` | 2.0.9 | no | Package | Settings |

VSCodium (`homeManager.vscode`, `vscodium`) is described in [MIMIR-VM.md](MIMIR-VM.md#vscodium); Okular comes with Plasma.

`nixos.desktop-kde` sets `NIXOS_OZONE_WL=1`, so the Electron and Chromium apps (VSCodium, Brave, Obsidian, Discord, Bitwarden, Spotify, Teams) run natively on Wayland.

## Services

System services come from NixOS modules in `modules/services/`, imported by the host.

| Service | Module | Version | Declared | Manual state |
| --- | --- | --- | --- | --- |
| Tailscale | `nixos.vpn` | 1.104.5 | `services.tailscale`, joining with the host's `tailscale_authkey` from nixos-secrets (see [SECRETS.md](SECRETS.md)) | Device keys in `/var/lib/tailscale` |
| Mullvad VPN | `nixos.vpn` | 2026.3 | `services.mullvad-vpn` with the desktop app (`mullvad-vpn`) | Account login, settings |
| eduVPN | `nixos.vpn` | 4.6.0 | Package, plus NetworkManager's OpenVPN plugin | Institution login, the NetworkManager connections it creates |
| Docker (rootless) | `nixos.docker` | 29.9.2 | `virtualisation.docker.rootless` with `DOCKER_HOST` set; no root daemon and no `docker` group | Images, containers, volumes in `~/.local/share/docker` |
| Wi-Fi, eduroam | `nixos.wifi` | — | NetworkManager profiles from `wifi_env` in nixos-secrets; eduroam per the University of Twente's CAT profile (see [SECRETS.md](SECRETS.md#eduroam)) | Other networks joined by hand |
| libvirt, virt-manager | `nixos.libvirt` | 12.2.0, 5.1.0 | `virtualisation.libvirtd`, `programs.virt-manager`; users need the `libvirtd` group, set by the host | VMs, networks, storage pools |

Docker is rootless because membership of a `docker` group is equivalent to root: any process of that user could start a container that mounts the whole disk. Rootless containers only have the user's own permissions. `mimir-vm-config` rejects a root daemon or `docker` group members. The `libvirtd` group is similarly powerful and must stay out of sandboxes.

## Language, formats and desktop

`nixos.workstation` sets British English as the language (`en_GB.UTF-8`) and Dutch formats for numbers, dates, the clock, currency, paper size and units (`nl_NL.UTF-8`).

`homeManager.desktop-kde` (`modules/desktop/environment/kde/settings.nix`) declares Plasma settings with [plasma-manager](https://github.com/nix-community/plasma-manager): the Breeze Dark theme, NumLock on at login, no overview at the top-left screen corner, the screen off and locked after ten minutes, no automatic suspend on mains power and after twenty minutes on battery, suspend when the lid closes. These are applied at every login; settings that are not declared keep what was chosen in System Settings. Panels, launchers, the touchpad and the mouse are not declared yet.

### Desktops and shortcuts

The same module (`modules/desktop/environment/kde/keyboard.nix`) declares the virtual desktops in one row. Their names are private and come from `desktop/desktops.json` in `nixos-secrets` (a plain list, in order, at most nine); the shortcuts and rules below are generated from it.

| Keys | Effect |
| --- | --- |
| `Meta+1` … `Meta+<n>` | Switch to that desktop (replaces Plasma's default for these keys, the n-th task-bar entry) |
| `Meta+Shift+1` … `Meta+Shift+<n>` | Move the active window to that desktop; stored as `Meta+!`, `Meta+@`, …, so it depends on the US keyboard layout |
| `Meta+Ctrl+Left` / `Right` | Previous and next desktop (Plasma default) |
| `Meta+PgUp` | Maximise or restore; new windows open maximised |
| `Alt+Space` | KRunner: applications, windows, and `<keyword>:<text>` for a web search. Added keywords: `scholar:` or `gs:` (Google Scholar), `arxiv:`, `nixopt:` (NixOS options); Plasma ships `dd:`, `wp:`, `gh:`, `doi:`, `pypi:`, `nixpkgs:` and many more |

**Brave windows on their desktop.** On Wayland a program cannot put its own windows back on a desktop, and every Brave window has the same class, so KWin places them by name. Name a window once (right-click the tab strip, "Name window…") as `<desktop>: <topic>`. It moves to that desktop at once and returns there whenever Brave creates it. The rule is forced: a named window cannot be moved to another desktop until it is renamed. Unnamed windows open on whichever desktop is current. The name replaces the page title in the task bar and in `Alt+Tab`.

**Brave brings its windows back.** Three parts, tested together in a VM (shutdown, logout, power loss):

- `brave-session` (`nixos.browser`) starts Brave at every login. After a crash or a power loss Brave would only offer "Restore pages?"; the script first marks the last exit as normal in Brave's `Preferences`, so the windows return unasked.
- Before Plasma ends a session, Brave is asked to exit as a whole (`modules/desktop/environment/kde/brave-session.nix`). Otherwise Plasma closes its windows one by one, Brave forgets some of them, and the shutdown waits two minutes. This replaces how Plasma starts its `plasma-shutdown` program for this user and relies on Plasma internals: **test a logout from the menu after every Plasma update**; deleting `~/.local/share/dbus-1/services/org.kde.Shutdown.service` restores the default.
- Plasma starts with an empty session, because its own restore would start Brave a second time. No other application reopens at login unless it is declared to start.

After a login the view is on the desktop of the window Brave restored last, not always on the first one.

## Default applications

`homeManager.default-apps` writes `~/.config/mimeapps.list`:

| Type | Opens in | Desktop file |
| --- | --- | --- |
| `x-scheme-handler/http`, `x-scheme-handler/https`, `text/html`, `application/xhtml+xml` | Brave | `brave-browser.desktop` |
| `application/pdf` | Okular | `okularApplication_pdf.desktop` |
| `x-scheme-handler/mailto` | Thunderbird | `thunderbird.desktop` |
| `text/x-tex` | VSCodium | `codium.desktop` |

The declared defaults win at every activation: Home Manager replaces `mimeapps.list` even if a program has rewritten it (`force = true`). Default applications changed in the GUI are therefore temporary and are lost at the next boot or rebuild; declare them here instead.

## Spell checking

`hunspellDicts.en_GB-ise` installs `en_GB.aff` and `en_GB.dic` into `/etc/profiles/per-user/<user>/share/hunspell` (NixOS links `share/hunspell` into profiles). LibreOffice's nixpkgs wrapper adds `share/hunspell` of every profile in `$NIX_PROFILES` to `DICPATH`. KDE apps use Sonnet, which searches `hunspell/` in every `$XDG_DATA_DIRS` entry, and the per-user profile's `share` is one of them. More languages: add further `hunspellDicts.*` packages next to it.

## Add a program

1. Check that the package exists in the pinned nixpkgs, and note its version, unfree status and `.desktop` files. From the repository, with `<attr>` replaced:

   ```bash
   vm='nixosConfigurations.mimir-vm'
   nix --extra-experimental-features 'nix-command flakes' \
     eval --raw "path:$PWD#$vm.pkgs.<attr>.version"
   ```

2. Add it to the fitting module in `modules/apps/`, or create a new file there that defines a new `flake.modules.homeManager.<name>` (or `flake.modules.nixos.<name>` for system-level programs). Every file under `modules/` must be a flake-parts module
3. Import a new module in the host (`modules/hosts/mimir-vm/default.nix`)
4. Add a row to the table above
5. Run the validation in [MIMIR-VM.md](MIMIR-VM.md#validate), rebuild, and relaunch the VM

## Add an unfree program

Unfree software is limited to an explicit allowlist. Evaluation fails with nixpkgs' "has an unfree license" error for anything else.

1. Add the package's name (`lib.getName`, usually the attribute name) to `allowUnfreePredicate` in `modules/flake/nixpkgs.nix`
2. Add the same name to `unfreeAllowed` in `modules/flake/checks.nix`; `mimir-vm-config` rejects unfree packages that are not on that list
3. Follow the steps in [Add a program](#add-a-program), and mark it unfree in the table
