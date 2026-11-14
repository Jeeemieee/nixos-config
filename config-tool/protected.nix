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
    # How the flake is put together: the checks, the package set, the hosts, the admin shell, the config command
    "modules/flake"
    # The development environments, their checks and the checks' scripts
    "dev-env"
    # Secrets, backup, disk, installer and boot: a wrong change loses data or access
    "modules/security"
    "modules/services/backup.nix"
    "modules/storage"
    "modules/install"
    "install"
    "modules/boot"
    # The accounts, sudo, the firewall and the Nix settings; and what each host is made of
    "modules/profiles"
    "modules/hosts"
    "modules/users"
    "modules/host-specification"
    # Where git and ssh run programs, and modules that carry a check of their own
    "modules/dev/git"
    "modules/dev/ssh.nix"
    "modules/services/search.nix"
    # Which versions of everything are used
    "flake.nix"
    "flake.lock"
    # Which files git leaves out of every status and commit
    ".gitignore"
    # What direnv evaluates in the user's own shell: its settings and this repository's .envrc
    "modules/dev/direnv.nix"
    ".envrc"
  ];
  nixos-secrets = [
    "AGENTS.md"
    # Who may decrypt, and the encrypted values
    ".sops.yaml"
    "secrets"
    # The instructions every agent gets, the list of hosts that ssh reads, and the desktops' names: plain files that become
    # part of the system
    "pi"
    "ssh"
    "desktop"
    ".gitignore"
  ];
}
