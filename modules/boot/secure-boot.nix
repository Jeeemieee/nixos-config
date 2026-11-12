# Secure Boot with lanzaboote; hosts opt in by importing nixos.secure-boot next to nixos.boot
# The machine generates its own signing keys on the first boot and enrolls them in the firmware at the next one,
# which requires the firmware's Secure Boot to be in setup mode once
{ inputs, config, ... }:
let
  topLevel = config;

  # lanzaboote's own test harness: a disk image booted with UEFI firmware that supports Secure Boot
  # These files are internal to lanzaboote and tied to the pinned version
  harness = "${inputs.lanzaboote}/nix/tests/lanzaboote/common";
in
{
  flake.modules.nixos.secure-boot =
    { lib, pkgs, ... }:
    {
      imports = [ inputs.lanzaboote.nixosModules.lanzaboote ];

      # lanzaboote installs and signs the boot files itself, with systemd-boot as the boot menu
      boot.loader.systemd-boot.enable = lib.mkForce false;

      boot.lanzaboote = {
        enable = true;
        # The private keys stay on this machine's encrypted disk
        pkiBundle = "/var/lib/sbctl";
        autoGenerateKeys.enable = true;
        autoEnrollKeys = {
          enable = true;
          # Needed for other systems on this machine (Ubuntu's boot loader) and for firmware components signed by Microsoft
          includeMicrosoftKeys = true;
        };
      };

      # Inspect the keys and the signatures: sbctl status, sbctl verify
      environment.systemPackages = [ pkgs.sbctl ];
    };

  perSystem =
    { pkgs, ... }:
    {
      # The module in a virtual machine with Secure Boot firmware: keys are generated, enrolled and enforced
      checks.secure-boot = pkgs.testers.runNixOSTest {
        name = "secure-boot";
        # Three boots; slow where the build users cannot use KVM
        globalTimeout = 40 * 60;

        nodes.machine =
          { lib, ... }:
          {
          imports = [
            "${harness}/lanzaboote.nix"
            topLevel.flake.modules.nixos.secure-boot
          ];

          # The harness sets image.repart.enable, which only newer NixOS has; in 26.05 importing the repart module enables it
          options.image.repart.enable = lib.mkOption {
            type = lib.types.bool;
            default = true;
          };

          config = {
            # No keys baked into the image, and a disk that keeps the generated ones
            lanzabooteTest = {
              keyFixture = false;
              persistentRoot = true;
            };
            virtualisation.tpm.enable = true;
            # Firmware with Secure Boot support, starting in setup mode (no keys enrolled)
            virtualisation.useSecureBoot = true;
          };
          };

        testScript =
          { nodes, ... }:
          (import "${harness}/image-helper.nix" { inherit (nodes) machine; })
          + ''
            keys = "/var/lib/sbctl/keys"

            with subtest("1. First boot: Secure Boot is off and the machine generates its own keys"):
                t.assertIn("Secure Boot: disabled", machine.succeed("bootctl status"))
                machine.wait_for_unit("generate-sb-keys.service")
                machine.succeed(f"test -s {keys}/db/db.key")
                machine.wait_for_unit("prepare-sb-auto-enroll.service")
                print(machine.succeed("ls /boot/loader/keys/auto"))
                fingerprint = machine.succeed(f"sha256sum {keys}/db/db.key {keys}/PK/PK.key")

            # The firmware starts the boot menu and the per-generation image; those must be signed
            # The kernel and initrd under EFI/nixos are not signed by design: the signed image holds their hashes and checks them (subtest 4)
            with subtest("3. Everything the firmware starts is signed with these keys"):
                verify = machine.succeed("sbctl verify")
                print(verify)
                results = [line for line in verify.splitlines() if line.startswith(("✓", "✗"))]
                unsigned = [line for line in results if line.startswith("✗")]
                t.assertGreaterEqual(len(results) - len(unsigned), 3)
                for line in unsigned:
                    t.assertRegex(line, r"^✗ /boot/EFI/nixos/kernel-[^/]+\.efi is not signed$")

            machine.reboot()

            with subtest("2. After a reboot the firmware enforces Secure Boot with these keys, and Microsoft's are enrolled"):
                t.assertIn("Secure Boot: enabled (user)", machine.succeed("bootctl status"))
                status = machine.succeed("sbctl status")
                print(status)
                t.assertIn("microsoft", status)

            with subtest("5. The keys are not generated again"):
                t.assertEqual(fingerprint, machine.succeed(f"sha256sum {keys}/db/db.key {keys}/PK/PK.key"))
                t.assertIn("start condition unmet", machine.fail("systemctl status generate-sb-keys.service"))
                t.assertIn("start condition unmet", machine.fail("systemctl status prepare-sb-auto-enroll.service"))

            with subtest("4. A tampered kernel is refused at boot"):
                machine.succeed("echo tampered | tee -a /boot/EFI/nixos/kernel-*.efi > /dev/null")
                machine.succeed("sync")
                machine.crash()
                machine.start()
                machine.wait_for_console_text("Kernel hash does not match")
          '';
      };
    };
}
