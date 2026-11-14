# Applications

Desktop applications come from the pinned nixpkgs (`flake.lock`) through shared modules in `modules/apps/`. Each host or user selects modules by importing them; the workstation profile (`modules/profiles/workstation.nix`) imports all of them for both hosts. Versions change only when `flake.lock` does. No program updates itself; only the three browser extensions that Brave is told to install come and update from the web store. Nothing here holds an account or credential: logins, accounts and libraries stay manual state on the machine.

## Programs

Versions are not listed here: they are whatever the current `flake.lock` pins, and they change with every `config update`. The command under [Add a program](#add-a-program) prints the version of any package.

| Program | Module | nixpkgs attribute | Unfree | Declared | Manual state |
| --- | --- | --- | --- | --- | --- |
| Brave | `nixos.browser` | `brave` | no | Package; managed policies in `/etc/brave/policies/managed/`: Rewards, Wallet, Brave VPN, Leo AI (`BraveAIChatEnabled`), P3A, the stats ping, Web Discovery and metrics reporting off; Bitwarden, Zotero Connector and Plasma Integration extensions force-installed and the built-in password manager off; the last session's windows and tabs reopen at every start (`RestoreOnStartup`); Memory Saver unloads tabs that have not been used for a while; the machine's own SearXNG as the search engine where `nixos.search` runs, Brave Search elsewhere (see [Search](#search)); spell checking in British English and Dutch; Safe Browsing at standard protection; bookmark bar and home button shown. A policy fixes its setting: the switch in Brave's settings is greyed out | Profile, sync, bookmarks, the extensions' logins, window names |
| Carlito, Caladea, Liberation | `nixos.fonts` | `carlito`, `caladea`, `liberation_ttf` | no | System fonts; fontconfig maps Calibri, Cambria, Arial, Times New Roman and Courier New to them | None |
| LibreOffice | `homeManager.office` | `libreoffice-qt6-still` | no | Package | User profile and settings |
| Scribus | `homeManager.office` | `scribus` | no | Package | Settings |
| Pympress | `homeManager.office` | `pympress` | no | Package | Settings |
| British English and Dutch dictionaries | `homeManager.office` | `hunspellDicts.en_GB-ise`, `hunspellDicts.nl_NL` | no | Hunspell dictionaries for LibreOffice and KDE apps (see [Spell checking](#spell-checking)) | Personal word lists |
| Thunderbird | `homeManager.mail` | `thunderbird` | no | Package; one default profile (`~/.thunderbird/default`) whose `user.js` sets `toolkit.telemetry.enabled`, `datareporting.healthreport.uploadEnabled`, `datareporting.policy.dataSubmissionEnabled` and `app.shield.optoutstudies.enabled` to false | Accounts, mail, calendars, address books |
| Obsidian | `homeManager.notes` | `obsidian` | yes | Package | Vaults and their settings (vault setup is Phase 4), Obsidian Sync login |
| Zotero | `homeManager.notes` | `zotero` | no | Package | Library, data directory, account and sync |
| GIMP | `homeManager.graphics` | `gimp` | no | Package | Settings, plug-ins |
| Inkscape | `homeManager.graphics` | `inkscape` | no | Package | Settings, extensions |
| Blender | `homeManager.graphics` | `blender` | no | Package | Preferences, add-ons |
| gThumb | `homeManager.graphics` | `gthumb` | no | Package | Settings, catalogues |
| ImageMagick | `homeManager.graphics` | `imagemagick` | no | Package (`magick`) | None |
| ParaView | `homeManager.engineering` | `paraview` | no | Package | Settings, state files |
| PrusaSlicer | `homeManager.engineering` | `prusa-slicer` | no | Package | Printer, filament and print profiles, Prusa account |
| fstl | `homeManager.engineering` | `fstl` | no | Package; a menu entry (`fstl.desktop`, nixpkgs installs none) | None |
| MeshLab | `homeManager.engineering` | `meshlab` | no | Package | Settings |
| gnuplot | `homeManager.engineering` | `gnuplot` | no | Package | None |
| TeX Live (full) | `homeManager.tex` | `texliveFull` | no | Package; every TeX Live package, including `pdflatex`, `lualatex` and `latexmk` | None |
| Discord | `homeManager.media` | `discord` | yes | Package | Login, servers; Discord downloads its own modules into `~/.config/discord` |
| Spotify | `homeManager.media` | `spotify` | yes | Package | Login, cache |
| VLC | `homeManager.media` | `vlc` | no | Package | Settings, playlists |
| ffmpeg | `homeManager.media` | `ffmpeg` | no | Package | None |
| Teams | `homeManager.meetings` | `teams-for-linux` | no | Package; unofficial client around Teams for the web | Work account login |
| Zoom | `homeManager.meetings` | `zoom-us` | yes | Package | Login |
| RustDesk | `homeManager.meetings` | `rustdesk-flutter` | no | Package; the Flutter client, since `rustdesk` depends on the unfree `libsciter` | ID, password, trusted devices |
| Bitwarden | `homeManager.passwords` | `bitwarden-desktop` | no | Package; starts with the desktop session, because its SSH agent serves the key for GitHub (see [GitHub access](#github-access)) | Login, vault, unlock settings, the "Enable SSH agent" switch, the SSH key item |
| Bitwarden CLI | `homeManager.passwords` | `bitwarden-cli` | no | Package (`bw`) | Login, session |
| Vim | `homeManager.cli` | `vim-full` (Home Manager's `programs.vim` default) | no | `programs.vim` with `defaultEditor`, so `EDITOR=vim` | None |
| btop | `homeManager.cli` | `btop` | no | `programs.btop` | None |
| tree | `homeManager.cli` | `tree` | no | Package | None |
| nmap | `homeManager.cli` | `nmap` | no | Package | None |
| TestDisk and PhotoRec | `homeManager.cli` | `testdisk` | no | Package; disk access needs `sudo` | None |
| smartmontools | `homeManager.cli` | `smartmontools` | no | Package (`smartctl`, needs `sudo`) | None |
| fastfetch | `homeManager.cli` | `fastfetch` | no | Package | None |
| tmux | `homeManager.cli` | `tmux` | no | `programs.tmux`, with mouse support and 50 000 lines of history; keeps shells and long runs alive when a terminal closes (`Ctrl+b d` detaches, `tmux attach` returns) | None |
| ncdu | `homeManager.cli` | `ncdu` | no | Package; shows what takes space in a folder such as `~/scratch` | None |
| pi (coding agent) | `homeManager.pi` | `pi-coding-agent` from nixos-unstable | no | Only as the sandboxed launcher `pi`; version check off, `pi update` points to Nix; instructions, settings and five extensions declared read-only (see [MIMIR-VM.md](MIMIR-VM.md#pi)) | Logins, sessions |
| Raspberry Pi Imager | `homeManager.rpi` | `rpi-imager` | no | Package | Settings |

VSCodium (`homeManager.vscode`, `vscodium`) is described in [MIMIR-VM.md](MIMIR-VM.md#vscodium); Okular comes with Plasma.

`nixos.desktop-kde` sets `NIXOS_OZONE_WL=1`, so the Electron and Chromium apps (VSCodium, Brave, Obsidian, Discord, Bitwarden, Spotify, Teams) run natively on Wayland.

## Services

System services come from NixOS modules in `modules/services/`, imported by the workstation profile (`modules/profiles/workstation.nix`); the backup only by the laptop.

| Service | Module | Declared | Manual state |
| --- | --- | --- | --- |
| Tailscale | `nixos.vpn` | `services.tailscale`, joining with the host's `tailscale_authkey` from nixos-secrets (see [SECRETS.md](SECRETS.md)) | Device keys in `/var/lib/tailscale` |
| Mullvad VPN | `nixos.vpn` | `services.mullvad-vpn` with the desktop app (`mullvad-vpn`) | Account login, settings |
| eduVPN | `nixos.vpn` | Package, plus NetworkManager's OpenVPN plugin | Institution login, the NetworkManager connections it creates |
| Docker (rootless) | `nixos.docker` | `virtualisation.docker.rootless` with `DOCKER_HOST` set; no root daemon and no `docker` group | Images, containers, volumes in `~/.local/share/docker` |
| Wi-Fi, eduroam | `nixos.wifi` | NetworkManager profiles from `wifi_env` in nixos-secrets; eduroam per the University of Twente's CAT profile (see [SECRETS.md](SECRETS.md#eduroam)) | Other networks joined by hand |
| SearXNG | `nixos.search` | `services.searx` on `127.0.0.1:8877`, from the `nixpkgs-search` pin (see [Search](#search)) | A generated key in `/var/lib/searx-secret` |
| libvirt, virt-manager | `nixos.libvirt` | `virtualisation.libvirtd`, `programs.virt-manager`; users need the `libvirtd` group, set by the workstation profile | VMs, networks, storage pools |

Docker is rootless because membership of a `docker` group is equivalent to root: any process of that user could start a container that mounts the whole disk. Rootless containers only have the user's own permissions. `mimir-vm-config` rejects a root daemon or `docker` group members. The `libvirtd` group is similarly powerful and must stay out of sandboxes.

## GitHub access

`homeManager.git` (`modules/dev/git/github.nix`) reaches GitHub over SSH with a key that lives in the Bitwarden vault. There is no key file and no token on the disk.

- The Bitwarden desktop app runs an SSH agent (socket `~/.bitwarden-ssh-agent.sock`) and answers while the vault is unlocked. `ssh` is told to use it for `github.com` only.
- GitHub's host keys are pinned (from `https://api.github.com/meta`): a server with another key is refused without a question. The check `github-host-key` tests that against a stand-in server, with a control.
- The user's own repositories go over SSH whatever address they were cloned with (`https://github.com/Jeeemieee/…` is rewritten), the private `nixos-secrets` input included. Other GitHub repositories keep HTTPS, so public ones can be fetched without a key.
- The pi sandbox sees neither the socket nor `~/.ssh` (`pi-sandbox` checks both), so an agent cannot push or fetch private repositories.

Once per Bitwarden account, by hand:

1. In the Bitwarden app: Settings, switch on "Enable SSH agent".
2. New item, type "SSH key"; Bitwarden generates the key. Copy its public key.
3. On GitHub: Settings, "SSH and GPG keys", "New SSH key", paste it.
4. Test: `ssh -T git@github.com` greets with the account name.

After every login the vault has to be unlocked once before git can reach GitHub. Not verified yet on NixOS: the agent itself, and whether `nix flake update nixos-secrets` honours the rewrite.

## SSH hosts

`homeManager.ssh` (`modules/dev/ssh.nix`) gives the SSH client the user's own list of hosts: clusters and servers with their addresses and user names. The list is private, not secret, and comes from `ssh/config` in nixos-secrets; it is an ordinary OpenSSH settings file.

- It is read **after** every declared host. ssh keeps the first value it finds for a setting, so the list cannot change what is declared, such as GitHub's pinned host keys. The check `ssh-settings` shows that with a stand-in list that tries to, and with a control in which the same list, read first, succeeds.
- Keys are not declared: a key named in the list must exist as a file in `~/.ssh` on the machine, or live in Bitwarden.
- To change the list: edit `ssh/config` in nixos-secrets, commit, `nix flake update nixos-secrets`, rebuild.
- Test a host without connecting: `ssh -G <name>` prints the address and user that would be used.

## Search

`nixos.search` (`modules/services/search.nix`) runs [SearXNG](https://docs.searxng.org), a meta-search: it asks several search engines and shows their results together, without ads; each result names the engines it came from. Every machine runs its own; it listens on `127.0.0.1:8877` only, so no other machine can use it. Its internal key is generated on the machine at the first start; there is no secret to enter.

Brave's address bar searches through it (`modules/apps/browser.nix` decides: SearXNG where the service runs, Brave Search elsewhere). No suggestions are requested while typing.

**Keywords.** In the address bar, a keyword, a space and the query search one site directly, without SearXNG:

| Keyword | Searches |
| --- | --- |
| `brave` | Brave Search; also the way to search while SearXNG is down or returns little |
| `google` | Google |
| `maps` | Google Maps (SearXNG's Map tab searches OpenStreetMap; it has no Google Maps engine) |
| `reddit` | Reddit |
| `github` | GitHub |
| `scholar` | Google Scholar |
| `arxiv` | arXiv |
| `doi` | Opens the paper that a DOI belongs to |
| `wiki` | Wikipedia (English) |
| `youtube` | YouTube |
| `nixpkgs`, `nixopt` | NixOS packages and options |
| `pypi` | Python packages |
| `scihub` | Sci-Hub, with a DOI or a paper's address; its own address changes now and then and is then updated in the list |

The list is in `modules/apps/browser.nix` (`SiteSearchSettings`). Backspace right after the space leaves the keyword mode and searches the word normally. The price of plain words: a normal search that starts with one of them and a space, such as "github actions cache", goes to that site instead of SearXNG.

Wikidata, which only fills the information box beside the results, is switched off: the page waits for its slowest engine, and in a measurement of six queries Wikidata took 0.9 s (median) where Google and Brave took 0.3 to 0.5 s.

**When it returns few or no results.** Search engines change their pages and block automated queries from time to time; the result page then lists per engine what went wrong ("CAPTCHA", "too many requests"). Two remedies:

- For one search, use the `brave` or `google` keyword. They also work while the service is down.
- If it stays that way, update SearXNG, which follows the engines' changes: `nix flake update nixpkgs-search`, run the checks and rebuild. SearXNG has its own pin for this reason; with the version of NixOS 26.05 only one of the default engines still answered.

Validation: the check `search` starts the service in a virtual machine without internet (it answers locally, another machine cannot reach it although the firewall is off, the key is private and not in the Nix store, and survives a restart). Results from the real engines need the internet; tested by hand in a VM on 2026-11-13: Google and Brave answered, DuckDuckGo intermittently.

## Language, formats and desktop

`nixos.workstation` sets British English as the language (`en_GB.UTF-8`), also for dates and the clock, so that the names of days and months are English (14/11/2026, 24-hour clock, weeks start on Monday). Numbers, currency, paper size and units follow the Dutch formats (`nl_NL.UTF-8`). glibc has no English locale with Dutch date formats (`en_NL`); `en_DK` would give English names with dates as 2026-11-14.

`homeManager.desktop-kde` (`modules/desktop/environment/kde/settings.nix`) declares Plasma settings with [plasma-manager](https://github.com/nix-community/plasma-manager): the Breeze Dark theme, NumLock on at login, no overview at the top-left screen corner, the screen off and locked after ten minutes, no automatic suspend on mains power and after twenty minutes on battery, suspend when the lid closes. These are applied at every login; settings that are not declared keep what was chosen in System Settings. The panel, the touchpad and the mouse are declared in `modules/desktop/environment/kde/panel.nix`: one panel at the bottom of every screen with Plasma's usual parts; the pinned programs Brave, Thunderbird, Dolphin, Konsole, Zotero, Obsidian, Kate and VSCodium; the windows of that screen and of the desktop in view; four small line charts for processor, memory, network and disk activity; the battery's percentage; week numbers in the calendar. The laptop's touchpad and the mouse on the 3Dconnexion receiver are set per device, by their names; another mouse keeps Plasma's defaults until it is added there.

### Desktops and shortcuts

The same module (`modules/desktop/environment/kde/keyboard.nix`) declares the virtual desktops in one row. Their names are private and come from `desktop/desktops.json` in `nixos-secrets` (a plain list, in order, at most nine); the shortcuts and rules below are generated from it.

| Keys | Effect |
| --- | --- |
| `Meta+1` … `Meta+<n>` | Switch to that desktop (replaces Plasma's default for these keys, the n-th task-bar entry) |
| `Meta+Shift+1` … `Meta+Shift+<n>` | Move the active window to that desktop; stored as `Meta+!`, `Meta+@`, …, so it depends on the US keyboard layout |
| `Meta+Ctrl+Left` / `Right` | Previous and next desktop (Plasma default) |
| `Meta+PgUp` | Maximise or restore; new windows open centred in their own size |
| `Alt+Space` | KRunner: applications, windows, and `<keyword>:<text>` for a web search. Added keywords: `scholar:` or `gs:` (Google Scholar), `arxiv:`, `nixopt:` (NixOS options); Plasma ships `dd:`, `wp:`, `gh:`, `doi:`, `pypi:`, `nixpkgs:` and many more |

**Brave windows on their desktop.** On Wayland a program cannot put its own windows back on a desktop, and every Brave window has the same class, so KWin places them by name. Name a window once (right-click the tab strip, "Name window…") as `<desktop>: <topic>`. It moves to that desktop at once and returns there whenever Brave creates it. The rule is forced: a named window cannot be moved to another desktop until it is renamed. Unnamed windows open on whichever desktop is current. The name replaces the page title in the task bar and in `Alt+Tab`.

**Brave brings its windows back.** Three parts, tested together in a VM (shutdown, logout, power loss):

- Brave is not started at login. Its launchers (application menu, task bar, links from other programs) start it through `brave-session` (`nixos.browser`), and the windows and tabs of the last session come back then. After a crash or a power loss Brave would only offer "Restore pages?"; the script first marks the last exit as normal in Brave's `Preferences`, so the windows return unasked. Started from a terminal as `brave`, that step is skipped.
- Before Plasma ends a session, Brave is asked to exit as a whole (`modules/desktop/environment/kde/brave-session.nix`). Otherwise Plasma closes its windows one by one, Brave forgets some of them, and the shutdown waits two minutes. This replaces how Plasma starts its `plasma-shutdown` program for this user and relies on Plasma internals: **test a logout from the menu after every Plasma update**; deleting `~/.local/share/dbus-1/services/org.kde.Shutdown.service` restores the default.
- Plasma starts with an empty session: no application reopens at login unless it is declared to start (Bitwarden is). Plasma's own restore would start Brave at login, with an extra window.

When Brave is opened, the view moves to the desktop of the window it restored last.

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
3. Import a new module in the workstation profile (`modules/profiles/workstation.nix`), which both hosts share
4. Add a row to the table above
5. Commit and rebuild as [UPKEEP.md](UPKEEP.md) describes (`config commit`, then `config switch` on the laptop or `config build mimir-vm vm` for the test VM)

## Add an unfree program

Unfree software is limited to an explicit allowlist. Evaluation fails with nixpkgs' "has an unfree license" error for anything else.

1. Add the package's name (`lib.getName`, usually the attribute name) to `allowUnfreePredicate` in `modules/flake/nixpkgs.nix`
2. Add the same name to `unfreeAllowed` in `modules/flake/checks.nix`; `mimir-vm-config` rejects unfree packages that are not on that list
3. Follow the steps in [Add a program](#add-a-program), and mark it unfree in the table
