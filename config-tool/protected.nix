# Protected paths
#
# What it is    The shared list of files and folders that an agent must not change without --unlock
# Who uses it   The pi launcher and the config command, with paths relative to each repository
# A caller adds A repository name below ~/repos and checks its paths against the matching list
# Protected     Yes: changing this list would change which safeguards apply (docs/UPKEEP.md)
{
  ## Part 1. Public system configuration
  # Protect the files that define the sandbox and its instructions
  nixos-config = [
    "modules/dev/pi.nix"
    "AGENTS.md"

    # Protect the worker setup: its limits, the queue's broker, the root helper with its sudo rule, and its checks
    "modules/dev/workers.nix"
    "workers"
    # The live overview is a program that the user runs on what agents wrote
    "workers-dashboard"

    # Protect the policy itself and the command that enforces it
    "config-tool"

    # Protect the flake wiring, checks, package set, hosts, admin shell and config command
    "modules/flake"

    # Protect the development environments and the tests that define their supported behaviour
    "dev-env"

    # Protect settings where a wrong change can lose data or access
    "modules/security"
    "modules/services/backup.nix"
    "modules/storage"
    "modules/install"
    "install"
    "modules/boot"

    # Protect the accounts, sudo, firewall, Nix settings and each host's composition
    "modules/profiles"
    "modules/hosts"
    "modules/users"

    # Protect places where Git and SSH run programs, and modules that carry their own checks
    "modules/dev/git"
    "modules/dev/ssh.nix"
    "modules/services/search.nix"

    # Protect version pins so an agent cannot replace the software sources
    "flake.nix"
    "flake.lock"

    # Protect ignored paths so changes cannot be hidden from status and commits
    ".gitignore"

    # Protect everything direnv evaluates in the user's own shell
    "modules/dev/direnv.nix"
    ".envrc"
  ];

  ## Part 2. Private configuration
  # Protect the instructions, decryption policy and encrypted values
  nixos-secrets = [
    "AGENTS.md"
    ".sops.yaml"
    "secrets"

    # Protect plain instructions and settings that become part of the system
    "pi"
    "ssh"
    "desktop"
    ".gitignore"
  ];
}
