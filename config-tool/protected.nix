# The files that decide what an agent may do, per repository below ~/repos; paths are relative to the repository
# A pi session sees them read-only unless it was started with --unlock, and a commit that touches one asks for a typed yes
# Read by the pi launcher (modules/dev/pi.nix) and by the config command (modules/flake/config-tool.nix): one list, two uses
{
  nixos-config = [
    # What an agent's sandbox is, and the instructions it gets
    "modules/dev/pi.nix"
    "AGENTS.md"
    # This list and the commit guard
    "config-tool"
    "modules/flake/config-tool.nix"
    # The checks, and what they are built from
    "modules/flake/checks.nix"
    "dev-env/checks.nix"
    # Secrets, backup, disk, installer and boot: a wrong change loses data or access
    "modules/security"
    "modules/services/backup.nix"
    "modules/storage"
    "modules/install"
    "install"
    "modules/boot"
    # Which versions of everything are used
    "flake.nix"
    "flake.lock"
    # Which files git leaves out of every status and commit
    ".gitignore"
    # What direnv evaluates in the user's own shell: its settings, this repository's .envrc, and the admin shell that it loads
    "modules/dev/direnv.nix"
    ".envrc"
    "modules/flake/shell.nix"
  ];
  nixos-secrets = [
    "AGENTS.md"
    # Who may decrypt, and the encrypted values
    ".sops.yaml"
    "secrets"
  ];
}
