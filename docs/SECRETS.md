# Secrets

Encrypted data lives in the private [nixos-secrets](https://github.com/Jeeemieee/nixos-secrets) repository; its README describes the files, keys and editing procedure. `flake.lock` pins its published revision. Fetching an uncached revision requires GitHub access on the build machine.

## Files and consumers

| Secret | File | Readable by | Used by |
| --- | --- | --- | --- |
| `wifi_env` | `secrets/shared.yaml` | admin, recovery, personal machines | `nixos.wifi`: NetworkManager profiles for eduroam, `home`, `gebbeken` and `hotspot` |
| `user_password_hash` | `secrets/shared.yaml` | admin, recovery, personal machines | `nixos.login-password` (on `mimir`): the account's password, with immutable accounts |
| `tailscale_authkey` | `secrets/<hostname>.yaml` | admin, recovery, that machine | `nixos.vpn`: `services.tailscale.authKeyFile` |
| `message` | `secrets/test.yaml` | development, mimir-vm, recovery | `nixos.secrets-test`: harmless bootstrap test |

Per-machine secrets are read from `secrets/${networking.hostName}.yaml`. Every secret is decrypted at boot into `/run/secrets/<name>`, root-owned with mode `0400`. The login password is the exception: it is decrypted into `/run/secrets-for-users` while the accounts are created, before any service runs. The machine's key must then already be on disk and enrolled, so a new machine's key is generated and enrolled during its installation, not at its first boot; without it the account has no password.

`secrets/mimir.yaml` exists before the laptop does: it is encrypted for the admin and recovery keys only, and the laptop's recipient is added when it is installed. Services that need them (`tailscaled-autoconnect`, `NetworkManager-ensure-profiles`) require and start after `sops-install-secrets.service`, so a failed decryption shows as a failed unit instead of a silent login without a key or empty Wi-Fi profiles.

The public repository only holds placeholders: network names, identities and passphrases are substituted into the NetworkManager profiles from the decrypted `wifi_env` at boot. A host that imports `nixos.wifi` without `hostSpec.hasSecrets = true` fails evaluation with an explicit message; `nixos.vpn` falls back to Tailscale's manual login (`sudo tailscale up`).

### eduroam

The profile follows the University of Twente's official eduroam CAT profile (cat.eduroam.org, profile 770): EAP-TTLS with MSCHAPv2, outer identity `anonymous@utwente.nl`, server name `radius.utwente.nl`, and the CA bundle `modules/services/certs/utwente-eduroam-ca.pem` (HARICA TLS RSA Root CA 2021 and the GEANT TLS RSA 1 intermediate). Validating the server certificate prevents fake eduroam access points from collecting the password. The `mimir-vm-eduroam-ca` check compares the bundle's SHA-256 fingerprints with the official profile.

## Policy

Real credentials are allowed in the VM: logging in by hand would store equivalent credentials on the same disk. The VM's identity is not encrypted at rest; anyone who can read the VM disk can obtain it. The VM disk stays on the laptop and is deleted after the migration.

## Key custody

- Admin (editing) key: `~/.config/sops/age/admin.age`, passphrase-protected; passphrase in Bitwarden ("nixos-secrets admin age key"). On every rule except the test secret
- Recovery key: Bitwarden only ("nixos-secrets recovery age key"); on every rule; never stored on a machine. Restore and recovery-only decryption tested on 2026-10-19
- Machine identity: `/var/lib/sops-nix/key.txt` (root-owned, mode `0600`, directory `0700`), generated on the machine by `sops-age-key.service`; never reuse it for another machine. Replacing the VM disk creates a new identity that needs enrolling; rebuilding with the same disk preserves it
- Old development key: `~/.config/sops/age/nixos-secrets-dev.agekey` on Ubuntu; only for the test secret, to be retired. It lived on a machine where agents ran unsandboxed, so it is not trusted for real secrets
- Keep private keys and plaintext outside both Git repositories and the Nix store, including ignored files
- Git on Ubuntu uses the plaintext `store` credential helper; use a secure helper on NixOS

Removing a recipient does not revoke old ciphertext or already-decrypted values; rotate affected credentials when access is revoked.

## Editing secrets

sops' own passphrase prompt goes through gpg-agent (a desktop pop-up, unreliable in terminals). The dev shell of this repository therefore sets `SOPS_AGE_KEY_CMD` to `age --decrypt ~/.config/sops/age/admin.age`, so age asks for the passphrase in the terminal, and provides `mkpasswd` for password hashes:

```bash
cd ~/repos/nixos-config
nix --extra-experimental-features 'nix-command flakes' develop "path:$PWD"
cd ~/repos/nixos-secrets
sops edit secrets/shared.yaml
```

Run the commands one at a time: lines pasted after `nix develop` can be lost while the shell starts. Then commit and push nixos-secrets and update the pin here with `nix flake update nixos-secrets`.

`wifi_env` is an environment file: one `NAME='value'` per line, every value in single quotes. The names must match the placeholders in `modules/services/wifi.nix`: `EDUROAM_IDENTITY`, `EDUROAM_PASSWORD`, and `<NETWORK>_SSID` and `<NETWORK>_PSK` for `HOME`, `GEBBEKEN` and `HOTSPOT`. To list the names without showing values:

```bash
sops decrypt --extract '["wifi_env"]' secrets/shared.yaml | sed -E "s/^([A-Z_]+)='.*'\$/\1 ok/; s/^([A-Z_]+)=.*/\1 NOT QUOTED/"
```

## Validation

From `~/repos/nixos-config`:

```bash
nix --extra-experimental-features 'nix-command flakes' flake check "path:$PWD"
```

The checks relevant here:

- `mimir-vm-secrets` builds the sops-nix manifest, which validates the pinned ciphertext without a private key: every declared secret must exist as a key in its file. It also asserts the secret list, their files, root ownership and mode, the key service's ordering, and the mode without secrets (`hasSecrets = false`): no secrets, manual Tailscale login, and the explicit refusal of `nixos.wifi`
- `mimir-vm-config` asserts the key source and permissions, Tailscale's key file and ordering, the eduroam settings, that Wi-Fi names and passphrases are placeholders, and the ordering of the profile service
- `mimir-vm-eduroam-ca` compares the eduroam CA bundle with the official fingerprints
- `mimir-vm-system` builds the VM's whole system closure

Decryption itself cannot be checked at build time; it is proven only in a VM whose recipient is enrolled. A fresh disk generates a new identity that the pinned ciphertext does not include, so `sops-install-secrets` fails there until it is enrolled; that is expected, not a fault.

### In the VM

```bash
systemctl is-active sops-age-key.service sops-install-secrets.service
sudo stat -Lc '%a %U:%G' /run/secrets/bootstrap-test /run/secrets/wifi_env /run/secrets/tailscale_authkey
sudo test -s /run/secrets/bootstrap-test && test ! -r /run/secrets/bootstrap-test && echo 'Test installed; normal-user access denied'
```

Expected: two `active` lines, `400 root:root` three times, and the final success message. These commands do not print any secret or private key.
