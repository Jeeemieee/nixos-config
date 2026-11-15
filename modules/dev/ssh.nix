# Private SSH host list
#
# What it is    A safe include of the private host names, addresses and account names from nixos-secrets
# Who uses it   A Home Manager user by importing homeManager.ssh; the workstation account imports it
# A user adds   ssh/config in nixos-secrets, while keys stay in ~/.ssh or Bitwarden
# Protected     Yes: SSH settings can execute code whenever a connection starts (docs/UPKEEP.md)
{ inputs, ... }@topLevel:
let
  # Keep private host details in the unencrypted private repository rather than publishing them here
  hostsFile = "${inputs.nixos-secrets}/ssh/config";
in
{
  ## Part 1. User configuration
  flake.modules.homeManager.ssh = {
    # Refuse an old secrets pin instead of quietly omitting every private host
    assertions = [
      {
        assertion = builtins.pathExists hostsFile;
        message = "homeManager.ssh needs ssh/config (the list of hosts) in the nixos-secrets input: update its pin with 'nix flake update nixos-secrets'";
      }
    ];

    programs.ssh = {
      # Ask Home Manager to write the user's SSH configuration
      enable = true;

      # Avoid inherited defaults so only reviewed settings apply to every host
      enableDefaultConfig = false;
      # Read the private list after declared hosts because SSH keeps the first value found for each setting
      # This prevents the include from replacing protected choices such as GitHub's pinned keys
      # The check below also limits the include because some SSH settings run programs or load libraries
      settings."*".Include = hostsFile;

      # Ask Bitwarden's agent for a key for every host, so a server's key is no file that a new machine lacks
      # The agent answers only while the desktop app runs and the vault is unlocked, and is not shared with a sandbox
      # A key file that the list names for a host is still tried
      settings."*".IdentityAgent = "~/.bitwarden-ssh-agent.sock";
    };
  };

  ## Part 2. Safety check
  perSystem =
    { pkgs, ... }:
    let
      # Inspect the exact SSH text produced for the test machine's user
      user = topLevel.config.flake.nixosConfigurations.mimir-vm.config.home-manager.users.jeeemieee;
      declared = user.home.file.".ssh/config".text;

      # Model a private list that tries to weaken the declared GitHub settings
      standIn = pkgs.writeText "ssh-hosts-stand-in" ''
        Host github.com
          User someone-else
          StrictHostKeyChecking no
          UserKnownHostsFile /dev/null
        Host cluster
          HostName cluster.example.org
          User researcher
      '';
      # Model settings that could run a program or load a library whenever SSH is used
      runsPrograms = pkgs.writeText "ssh-hosts-running-programs" ''
        Host cluster
          HostName cluster.example.org
          ProxyCommand sh -c "touch /tmp/marker; exit 1"
        Match exec "touch /tmp/marker"
          User researcher
        Host other
          PKCS11Provider=/tmp/library.so
      '';
      # Allow only connection details, identity selection, keepalives and compression
      # The real list also uses agent key storage and remote windows
      # Those last features keep keys in the agent and show windows from a remote program locally
      allowedSettings = "host hostname user port identityfile identitiesonly proxyjump serveraliveinterval serveralivecountmax compression addkeystoagent forwardx11";
    in
    {
      # Prove declared GitHub safeguards win and ordinary private hosts work
      # Unsafe settings must be reported by name only
      checks.ssh-settings =
        pkgs.runCommand "ssh-settings-check"
          {
            nativeBuildInputs = [
              pkgs.openssh
              pkgs.gawk
            ];
          }
          ''
            ## Step 1. Prepare helpers and an isolated SSH home
            export HOME=$TMPDIR
            failed=0
            expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; failed=1; fi; }
            value() { ssh -F "$1" -G "$2" | sed -n "s/^$3 //p" | head -n 1; }

            ## Step 2. Replace the private include with the safe stand-in
            # Copy it because SSH refuses configuration owned by another account
            # Store files have that ownership inside a build
            cp ${standIn} "$PWD/list" && chmod 600 "$PWD/list"
            sed "s|${hostsFile}|$PWD/list|" ${pkgs.writeText "ssh-config-declared" declared} > declared
            grep -q "Include $PWD/list" declared || { echo "FAIL: the declared settings do not include the list of hosts"; exit 1; }
            # Let SSH show its own error if the completed configuration cannot be read
            ssh -F declared -G github.com > /dev/null || { echo "FAIL: ssh cannot read the declared settings"; exit 1; }

            ## Step 3. Prove the declared GitHub values win and a private host still works
            expect "GitHub's user" "$(value declared github.com user)" git
            expect "GitHub's host key check" "$(value declared github.com stricthostkeychecking)" true
            # ssh prints the path with ~ replaced by the home folder
            expect "GitHub's key service" "$(value declared github.com identityagent)" "$HOME/.bitwarden-ssh-agent.sock"
            expect "GitHub's known hosts" "$(value declared github.com userknownhostsfile | grep -c github-known-hosts)" 1
            expect "a host of the list: address" "$(value declared cluster hostname)" cluster.example.org
            expect "a host of the list: user" "$(value declared cluster user)" researcher
            # A key in Bitwarden serves every host, so no key file has to exist on a new machine
            expect "a host of the list: key service" "$(value declared cluster identityagent)" "$HOME/.bitwarden-ssh-agent.sock"

            ## Step 4. Control that include order is the safeguard
            # Reading the same list first must change GitHub's settings
            { echo "Include $PWD/list"; grep -v "Include $PWD/list" declared; } > list-first
            expect "control: the list read first changes GitHub's user" "$(value list-first github.com user)" someone-else
            expect "control: and switches the host key check off" "$(value list-first github.com stricthostkeychecking)" false

            ## Step 5. Refuse private-list settings outside the agreed set
            # Other SSH settings can run programs or load libraries whenever a connection starts
            # Print only the line number and setting name because the list itself is private
            notAllowed() {
              awk -v allowed="${allowedSettings}" '
                BEGIN { count = split(allowed, names, " "); for (i = 1; i <= count; i++) agreed[names[i]] = 1 }
                { line = $0; sub(/^[ \t]+/, "", line); if (line == "" || line ~ /^#/) next
                  name = tolower(line); sub(/[ \t=].*$/, "", name)
                  if (!(name in agreed)) print "line " NR ": " name }' "$1" | tr '\n' ';'
            }
            expect "the private list of hosts holds only agreed settings" "$(notAllowed ${hostsFile})" ""
            expect "control: a list with two other settings" "$(notAllowed ${standIn})" "line 3: stricthostkeychecking;line 4: userknownhostsfile;"
            expect "a list with settings that run programs" "$(notAllowed ${runsPrograms})" "line 3: proxycommand;line 4: match;line 7: pkcs11provider;"

            ## Step 6. Fail after showing every mismatch
            [ "$failed" = 0 ] || exit 1
            touch "$out"
          '';
    };
}
