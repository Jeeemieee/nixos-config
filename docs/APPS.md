# Applications

Desktop applications come from the pinned nixpkgs (`flake.lock`) through shared modules in `modules/apps/`. Each host or user selects modules by importing them; `mimir-vm` imports all of them (see [MIMIR-VM.md](MIMIR-VM.md)). Versions change only when `flake.lock` does. Nothing here updates itself, and nothing here holds an account or credential: logins, accounts and libraries stay manual state inside the VM.

## Programs

Versions are those of the current `flake.lock` (nixos-26.05).

| Program | Module | nixpkgs attribute | Version | Unfree | Declared | Manual state |
| --- | --- | --- | --- | --- | --- | --- |
| Brave | `nixos.browser` | `brave` | 1.99.55 | no | Package; managed policies in `/etc/brave/policies/managed/`: Rewards, Wallet, Brave VPN, Leo AI (`BraveAIChatEnabled`), P3A, the stats ping, Web Discovery and metrics reporting off; Bitwarden extension force-installed | Profile, sync, bookmarks, the Bitwarden extension's login |
| Carlito, Caladea, Liberation | `nixos.fonts` | `carlito`, `caladea`, `liberation_ttf` | 20130920, 20130214, 2.1.5 | no | System fonts; fontconfig maps Calibri, Cambria, Arial, Times New Roman and Courier New to them | None |
| LibreOffice | `homeManager.office` | `libreoffice-qt6-still` | 25.8.5.2 | no | Package | User profile and settings |
| Scribus | `homeManager.office` | `scribus` | 1.7.3 | no | Package | Settings |
| Pympress | `homeManager.office` | `pympress` | 1.8.6 | no | Package | Settings |
| English (US) dictionary | `homeManager.office` | `hunspellDicts.en_US` | 2026.02.25 | no | Hunspell dictionary for LibreOffice and KDE apps (see [Spell checking](#spell-checking)) | Personal word lists |
| Thunderbird | `homeManager.mail` | `thunderbird` | 159.0 | no | Package; one default profile (`~/.thunderbird/default`) whose `user.js` sets `toolkit.telemetry.enabled`, `datareporting.healthreport.uploadEnabled`, `datareporting.policy.dataSubmissionEnabled` and `app.shield.optoutstudies.enabled` to false | Accounts, mail, calendars, address books |
| Obsidian | `homeManager.notes` | `obsidian` | 1.13.7 | yes | Package | Vaults and their settings (vault setup is Phase 4), Obsidian Sync login |
| Zotero | `homeManager.notes` | `zotero` | 9.0.6 | no | Package | Library, data directory, account and sync, connectors |
| GIMP | `homeManager.graphics` | `gimp` | 3.0.8 | no | Package | Settings, plug-ins |
| Inkscape | `homeManager.graphics` | `inkscape` | 1.4.4 | no | Package | Settings, extensions |
| Blender | `homeManager.graphics` | `blender` | 5.1.1 | no | Package | Preferences, add-ons |
| ParaView | `homeManager.engineering` | `paraview` | 6.0.1 | no | Package | Settings, state files |
| PrusaSlicer | `homeManager.engineering` | `prusa-slicer` | 2.9.4 | no | Package | Printer, filament and print profiles, Prusa account |
| fstl | `homeManager.engineering` | `fstl` | 0.11.1 | no | Package; a menu entry (`fstl.desktop`, nixpkgs installs none) | None |
| Discord | `homeManager.media` | `discord` | 1.0.159 | yes | Package | Login, servers; Discord downloads its own modules into `~/.config/discord` |
| Spotify | `homeManager.media` | `spotify` | 1.2.90.451 | yes | Package | Login, cache |
| Bitwarden | `homeManager.passwords` | `bitwarden-desktop` | 2026.8.0 | no | Package | Login, vault, unlock settings |
| Bitwarden CLI | `homeManager.passwords` | `bitwarden-cli` | 2026.4.2 | no | Package (`bw`) | Login, session |
| Vim | `homeManager.cli` | `vim-full` (Home Manager's `programs.vim` default) | 9.2.1252 | no | `programs.vim` with `defaultEditor`, so `EDITOR=vim` | None |
| btop | `homeManager.cli` | `btop` | 1.4.8 | no | `programs.btop` | None |
| tree | `homeManager.cli` | `tree` | 2.3.2 | no | Package | None |

VSCodium (`homeManager.vscode`, `vscodium`) is described in [MIMIR-VM.md](MIMIR-VM.md#vscodium); Okular comes with Plasma.

`nixos.desktop-kde` sets `NIXOS_OZONE_WL=1`, so the Electron and Chromium apps (VSCodium, Brave, Obsidian, Discord, Bitwarden, Spotify) run natively on Wayland.

## Default applications

`homeManager.default-apps` writes `~/.config/mimeapps.list`:

| Type | Opens in | Desktop file |
| --- | --- | --- |
| `x-scheme-handler/http`, `x-scheme-handler/https` | Brave | `brave-browser.desktop` |
| `application/pdf` | Okular | `okularApplication_pdf.desktop` |
| `x-scheme-handler/mailto` | Thunderbird | `thunderbird.desktop` |
| `text/x-tex` | VSCodium | `codium.desktop` |

The declared defaults win at every activation: Home Manager replaces `mimeapps.list` even if a program has rewritten it (`force = true`). Default applications changed in the GUI are therefore temporary and are lost at the next boot or rebuild; declare them here instead.

## Spell checking

`hunspellDicts.en_US` installs `en_US.aff` and `en_US.dic` into `/etc/profiles/per-user/<user>/share/hunspell` (NixOS links `share/hunspell` into profiles). LibreOffice's nixpkgs wrapper adds `share/hunspell` of every profile in `$NIX_PROFILES` to `DICPATH`. KDE apps use Sonnet, which searches `hunspell/` in every `$XDG_DATA_DIRS` entry, and the per-user profile's `share` is one of them. More languages: add further `hunspellDicts.*` packages next to it.

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
