# The user's own list of SSH hosts (clusters, servers); users opt in by importing homeManager.ssh
# The list names hosts, addresses and user names: private, not secret. It comes from ssh/config in nixos-secrets (plain, not encrypted)
# Keys are not declared here: they stay files in ~/.ssh or live in Bitwarden
{ inputs, ... }@topLevel:
let
  hostsFile = "${inputs.nixos-secrets}/ssh/config";
in
{
  flake.modules.homeManager.ssh = {
    # Without this, a nixos-secrets pin from before the file existed would quietly give an SSH client without the hosts
    assertions = [
      {
        assertion = builtins.pathExists hostsFile;
        message = "homeManager.ssh needs ssh/config (the list of hosts) in the nixos-secrets input: update its pin with 'nix flake update nixos-secrets'";
      }
    ];

    programs.ssh = {
      enable = true;
      # Home Manager's former defaults for every host are not wanted; only what is declared applies
      enableDefaultConfig = false;
      # Read after every declared host: ssh keeps the first value it finds for a setting, so the list cannot change what is declared, such as GitHub's pinned keys
      # What the list may hold is limited by the ssh-settings check below: ssh has settings that run a program or load a library
      settings."*".Include = hostsFile;
    };
  };

  perSystem =
    { pkgs, ... }:
    let
      user = topLevel.config.flake.nixosConfigurations.mimir-vm.config.home-manager.users.jeeemieee;
      declared = user.home.file.".ssh/config".text;
      # A list that tries to change what is declared for GitHub
      standIn = pkgs.writeText "ssh-hosts-stand-in" ''
        Host github.com
          User someone-else
          StrictHostKeyChecking no
          UserKnownHostsFile /dev/null
        Host cluster
          HostName cluster.example.org
          User researcher
      '';
      # A list with settings that run a program, or load a library, on this machine whenever ssh is used
      runsPrograms = pkgs.writeText "ssh-hosts-running-programs" ''
        Host cluster
          HostName cluster.example.org
          ProxyCommand sh -c "touch /tmp/marker; exit 1"
        Match exec "touch /tmp/marker"
          User researcher
        Host other
          PKCS11Provider=/tmp/library.so
      '';
      # The settings a list of hosts may hold: where a host is, who logs in, with which key, and through which other host;
      # and the two more that the user's own list uses, keys kept in the agent and windows of a remote program shown here
      allowedSettings = "host hostname user port identityfile identitiesonly proxyjump serveraliveinterval serveralivecountmax compression addkeystoagent forwardx11";
    in
    {
      # The declared settings for GitHub hold whatever the private list of hosts says, and the list's own hosts work
      checks.ssh-settings =
        pkgs.runCommand "ssh-settings-check"
          {
            nativeBuildInputs = [
              pkgs.openssh
              pkgs.gawk
            ];
          }
          ''
            export HOME=$TMPDIR
            failed=0
            expect() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2 (expected $3)"; failed=1; fi; }
            value() { ssh -F "$1" -G "$2" | sed -n "s/^$3 //p" | head -n 1; }

            # The declared file, with the stand-in list in place of the private one; it must have named the private list
            # ssh refuses a settings file that belongs to someone else, as store files do inside a build, so the stand-in is copied here
            cp ${standIn} "$PWD/list" && chmod 600 "$PWD/list"
            sed "s|${hostsFile}|$PWD/list|" ${pkgs.writeText "ssh-config-declared" declared} > declared
            grep -q "Include $PWD/list" declared || { echo "FAIL: the declared settings do not include the list of hosts"; exit 1; }
            # ssh must be able to read the file at all; its own message is shown if it cannot
            ssh -F declared -G github.com > /dev/null || { echo "FAIL: ssh cannot read the declared settings"; exit 1; }

            expect "GitHub's user" "$(value declared github.com user)" git
            expect "GitHub's host key check" "$(value declared github.com stricthostkeychecking)" true
            # ssh prints the path with ~ replaced by the home folder
            expect "GitHub's key service" "$(value declared github.com identityagent)" "$HOME/.bitwarden-ssh-agent.sock"
            expect "GitHub's known hosts" "$(value declared github.com userknownhostsfile | grep -c github-known-hosts)" 1
            expect "a host of the list: address" "$(value declared cluster hostname)" cluster.example.org
            expect "a host of the list: user" "$(value declared cluster user)" researcher

            # Control: read before the declared hosts, the same list does change GitHub's settings
            { echo "Include $PWD/list"; grep -v "Include $PWD/list" declared; } > list-first
            expect "control: the list read first changes GitHub's user" "$(value list-first github.com user)" someone-else
            expect "control: and switches the host key check off" "$(value list-first github.com stricthostkeychecking)" false

            # The list may only hold settings from an agreed set: ssh's other settings include ones that run a program
            # (ProxyCommand, LocalCommand, Match exec, KnownHostsCommand) or load a library (PKCS11Provider), at every use of ssh
            # Only the line's number and the setting's name are printed: the list is private
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

            [ "$failed" = 0 ] || exit 1
            touch "$out"
          '';
    };
}
