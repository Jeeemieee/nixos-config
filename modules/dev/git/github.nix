# GitHub over SSH with a key that lives in Bitwarden; part of homeManager.git, next to identity.nix
# The Bitwarden desktop app hands the key to git while the vault is unlocked (Settings, "Enable SSH agent"); no key file is on the disk
# Once per Bitwarden account, by hand: create an SSH key item in the vault and add its public key to GitHub
{ ... }@topLevel:
let
  # GitHub's public host keys, from https://api.github.com/meta ("ssh_keys"); a server that presents another key is refused
  githubHostKeys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg="
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk="
  ];
  knownHostsFile =
    pkgs:
    pkgs.writeText "github-known-hosts" (
      pkgs.lib.concatMapStrings (key: "github.com ${key}\n") githubHostKeys
    );
in
{
  flake.modules.homeManager.git =
    { pkgs, ... }:
    {
      programs.ssh = {
        enable = true;
        # Home Manager's former defaults for every host are not wanted; only what is declared here applies
        enableDefaultConfig = false;
        matchBlocks."github.com" = {
          user = "git";
          # The socket of the Bitwarden desktop app's SSH agent; it exists while the app runs
          identityAgent = "~/.bitwarden-ssh-agent.sock";
          extraOptions = {
            # Only the pinned keys count: no question to trust a new key, and nothing is learned from the network
            StrictHostKeyChecking = "yes";
            UserKnownHostsFile = "${knownHostsFile pkgs}";
          };
        };
      };

      # The user's own repositories go over SSH whatever address they were cloned with, the private nixos-secrets input included
      # Other GitHub repositories keep HTTPS, so that public ones can still be fetched without a key, also inside the pi sandbox
      programs.git.settings.url."git@github.com:Jeeemieee/".insteadOf = "https://github.com/Jeeemieee/";
    };

  perSystem =
    { pkgs, ... }:
    let
      user = topLevel.config.flake.nixosConfigurations.mimir-vm.config.home-manager.users.jeeemieee;
      sshConfig = user.home.file.".ssh/config".source;
    in
    {
      # The declared SSH settings against a stand-in for github.com with another host key: it must be refused without a question
      checks.github-host-key = pkgs.testers.runNixOSTest {
        name = "github-host-key";

        nodes.impostor = {
          services.openssh.enable = true;
          users.users.git = {
            isNormalUser = true;
          };
        };
        nodes.client =
          { nodes, ... }:
          {
            # In this test network the name github.com leads to the stand-in
            networking.extraHosts = "${nodes.impostor.networking.primaryIPAddress} github.com";
          };

        testScript = ''
          start_all()
          impostor.wait_for_unit("sshd.service")
          client.wait_for_unit("multi-user.target")
          client.succeed("ping -c 1 github.com")

          ssh = "ssh -F ${sshConfig} -o BatchMode=yes -o ConnectTimeout=10"

          with subtest("G1: a server with another host key is refused, without a question"):
              status, output = client.execute(f"{ssh} git@github.com true 2>&1")
              assert status != 0 and "Host key verification failed" in output, output

          with subtest("G2 (control): with the stand-in's own key accepted, the same command gets past the host key and fails at the login instead"):
              client.succeed("ssh-keyscan github.com > /tmp/standin-known-hosts 2>/dev/null && test -s /tmp/standin-known-hosts")
              status, output = client.execute(f"{ssh} -o UserKnownHostsFile=/tmp/standin-known-hosts git@github.com true 2>&1")
              assert status != 0 and "Host key verification failed" not in output and "Permission denied" in output, output

          with subtest("G3: nothing was learned: the pinned file is unchanged and no other known-hosts file was written"):
              client.succeed("grep -q 'UserKnownHostsFile ${knownHostsFile pkgs}' ${sshConfig}")
              client.succeed("test \"$(sha256sum < ${knownHostsFile pkgs})\" = \"$(printf '%s\\n' ${
                pkgs.lib.concatMapStringsSep " " (key: pkgs.lib.escapeShellArg "github.com ${key}") githubHostKeys
              } | sha256sum)\"")
              client.fail("test -e /root/.ssh/known_hosts")
        '';
      };
    };
}
