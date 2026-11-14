# GitHub SSH access
#
# What it is    Pinned GitHub host keys and Git transport through Bitwarden's SSH agent
# Who uses it   The Home Manager git module beside identity.nix
# A user adds   One SSH key item in Bitwarden and its public key in the GitHub account
# Protected     Yes: this decides which server Git trusts and which agent supplies the key (docs/UPKEEP.md)
{ ... }@topLevel:
let
  ## Part 1. Trusted GitHub host keys
  # Pin GitHub's published ssh_keys so a server presenting any other key is refused
  githubHostKeys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg="
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk="
  ];
  # Write the pinned keys in the known-hosts format understood by OpenSSH
  knownHostsFile =
    pkgs:
    pkgs.writeText "github-known-hosts" (
      pkgs.lib.concatMapStrings (key: "github.com ${key}\n") githubHostKeys
    );
in
{
  ## Part 2. User SSH and Git settings
  flake.modules.homeManager.git =
    { pkgs, ... }:
    {
      programs.ssh = {
        # Ask Home Manager to write the user's SSH configuration
        enable = true;

        # Avoid inherited defaults so only the settings reviewed here apply to GitHub
        enableDefaultConfig = false;
        settings."github.com" = {
          # GitHub's SSH service always uses this account name
          User = "git";

          # Use Bitwarden's agent socket, which exists only while the desktop app runs
          IdentityAgent = "~/.bitwarden-ssh-agent.sock";
          # Trust only the pinned keys without prompting or learning a replacement from the network
          StrictHostKeyChecking = "yes";
          UserKnownHostsFile = "${knownHostsFile pkgs}";
        };
      };

      # Rewrite only the user's own repositories to SSH, including the private configuration input
      # Leave other GitHub addresses on HTTPS so public repositories remain available without a key
      # This also keeps them fetchable inside the sandbox
      programs.git.settings.url."git@github.com:Jeeemieee/".insteadOf = "https://github.com/Jeeemieee/";
    };

  ## Part 3. Host-key refusal test
  perSystem =
    { pkgs, ... }:
    let
      # Reuse the exact SSH configuration produced for the test machine's user
      user = topLevel.config.flake.nixosConfigurations.mimir-vm.config.home-manager.users.jeeemieee;
      sshConfig = user.home.file.".ssh/config".source;
    in
    {
      # Put an impostor at GitHub's name and prove the pinned configuration refuses it without asking
      checks.github-host-key = pkgs.testers.runNixOSTest {
        name = "github-host-key";

        nodes.impostor = {
          # Provide an SSH server whose generated host key is not in the pinned list
          services.openssh.enable = true;
          # Let the control case reach login after accepting the impostor's own key
          users.users.git = {
            isNormalUser = true;
          };
        };
        nodes.client =
          { nodes, ... }:
          {
            # Point GitHub's public name at the impostor only inside the test network
            networking.extraHosts = "${nodes.impostor.networking.primaryIPAddress} github.com";
          };

        testScript = ''
          ## Step 1. Start both machines and prove the test name is reachable
          start_all()
          impostor.wait_for_unit("sshd.service")
          client.wait_for_unit("multi-user.target")
          client.succeed("ping -c 1 github.com")

          ## Step 2. Build one non-interactive command from the declared configuration
          ssh = "ssh -F ${sshConfig} -o BatchMode=yes -o ConnectTimeout=10"

          ## Step 3. Refuse the impostor with the pinned keys
          with subtest("G1: a server with another host key is refused, without a question"):
              status, output = client.execute(f"{ssh} git@github.com true 2>&1")
              assert status != 0 and "Host key verification failed" in output, output

          ## Step 4. Control that the connection reaches login when the impostor key is accepted
          with subtest("G2 (control): with the stand-in's own key accepted, the same command gets past the host key and fails at the login instead"):
              client.succeed("ssh-keyscan github.com > /tmp/standin-known-hosts 2>/dev/null && test -s /tmp/standin-known-hosts")
              status, output = client.execute(f"{ssh} -o UserKnownHostsFile=/tmp/standin-known-hosts git@github.com true 2>&1")
              assert status != 0 and "Host key verification failed" not in output and "Permission denied" in output, output

          ## Step 5. Prove the refusal learned and wrote nothing
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
