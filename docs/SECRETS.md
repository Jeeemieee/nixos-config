# Secrets

Encrypted data lives in the private [nixos-secrets](https://github.com/Jeeemieee/nixos-secrets) repository. `flake.lock` pins its published revision; existing public dependency versions are unchanged. Fetching an uncached revision requires GitHub access on the build machine.

## Current stage: test-secret decryption verified

The VM's public recipient was enrolled in secrets commit `6b71eb46900f026889995a1f14b0f6fe5d41a966`, now pinned here. `hostSpec.hasSecrets = true` enables only the harmless test secret. The user confirmed both services active and `400 root:root` permissions in the actual VM, including after reboot. No production credentials are configured.

The reusable modules in `modules/core/security/personal-secrets.nix` preserve the guest's identity at `/var/lib/sops-nix/key.txt` (root-owned, mode `0600`, directory `0700`). The Ubuntu development identity is never copied into the VM. After the key service succeeds, `sops-nix` decrypts `message` into `/run/secrets/bootstrap-test`, root-owned with mode `0400`.

Fully shut down the older QEMU instance, then launch the rebuilt `result` using the **same guest disk**, as described in [MIMIR-VM.md](MIMIR-VM.md). In the VM's Konsole:

```bash
systemctl is-active sops-age-key.service sops-install-secrets.service
sudo stat -Lc '%a %U:%G' /run/secrets/bootstrap-test
sudo test -s /run/secrets/bootstrap-test && test ! -r /run/secrets/bootstrap-test && echo 'Test installed; normal-user access denied'
```

Expected: two `active` lines, `400 root:root`, and the final success message. These commands do not print the secret or private key. Reboot the VM and repeat them to confirm runtime decryption and identity persistence.

For a replacement disk or another machine, enroll its own public recipient first: add it to `.sops.yaml`, rewrap the appropriate encrypted file, review/publish the changes, and pin that revision. Editing the recipient rule alone is not enough. Enrollment-only configurations can leave `hostSpec.hasSecrets = false` to generate an identity without attempting decryption.

## Key custody

- Ubuntu test editing key: `~/.config/sops/age/nixos-secrets-dev.agekey`
- VM test identity: `/var/lib/sops-nix/key.txt` inside the guest disk; never reuse it for a different machine
- Bitwarden can hold a private-key backup; test restoration and maintain independent recovery before introducing important credentials
- Keep private keys and plaintext outside both Git repositories and the Nix store, including ignored files. The development and experimental VM identities remain test-only
- The guest's key is not encrypted at rest by this setup. Anyone who can read the VM disk can obtain it; keep production credentials out of this experimental VM
- Replacing the guest disk creates a new identity and requires enrollment again. Rebuilding with the same disk preserves it
- Git currently uses the plaintext `store` credential helper. Move to a secure helper before using this workstation for long-term secrets administration

Removing a recipient does not revoke old ciphertext or already-decrypted values; rotate affected credentials when access is revoked.

## Validation

From `~/repos/nixos-config`:

```bash
nix --extra-experimental-features 'nix-command flakes' flake check --no-write-lock-file "path:$PWD"
```

The checks relevant here:

- `mimir-vm-secrets` builds the sops-nix manifest, which validates the pinned ciphertext's structure without a private key, and asserts the secret's owner and mode, the key service's ordering, and the enrollment-only mode (`hasSecrets = false`)
- `mimir-vm-config` asserts the key source and the key directory's mode and umask
- `mimir-vm-system` builds the VM's whole system closure

Decryption itself cannot be checked at build time. It is proven only in a VM whose recipient is enrolled, using the commands above. A fresh disk generates a new identity that the pinned ciphertext does not include, so `sops-install-secrets` fails there until it is enrolled; that is expected, not a fault.

Do not enable the inherited `core` group for secrets support: its old `sops.nix` still refers to the friend's removed input. Use the separate personal modules above.
