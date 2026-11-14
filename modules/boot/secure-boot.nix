# Secure Boot
#
# What it is    Lanzaboote signing, local key generation and automatic firmware enrolment
# Who uses it   A physical NixOS host by importing nixos.secure-boot beside nixos.boot
# A host adds   Firmware in setup mode for one boot so the machine can enrol its new keys
# Protected     Yes: a wrong boot or signing change can make the machine inaccessible (docs/SECURE-BOOT.md)
{ inputs, config, ... }:
let
  # Keep the complete flake module set available inside the per-system test definition
  topLevel = config;

  # Use lanzaboote's matching UEFI test harness from the pinned source
  # These files are internal to lanzaboote and therefore tied to that exact version
  harness = "${inputs.lanzaboote}/nix/tests/lanzaboote/common";
in
{
  ## Part 1. Host module
  flake.modules.nixos.secure-boot =
    { lib, pkgs, ... }:
    {
      # Add lanzaboote's options and boot implementation
      imports = [ inputs.lanzaboote.nixosModules.lanzaboote ];

      # Let lanzaboote install and sign the boot files while systemd-boot remains the menu
      boot.loader.systemd-boot.enable = lib.mkForce false;

      boot.lanzaboote = {
        # Turn on signed unified kernel images for this host
        enable = true;

        # Keep the private signing keys on this machine's encrypted disk
        pkiBundle = "/var/lib/sbctl";
        # Create a new key set on the first boot instead of storing keys in this repository
        autoGenerateKeys.enable = true;

        autoEnrollKeys = {
          # Enrol the generated keys after firmware setup mode has allowed the change
          enable = true;

          # Keep other operating systems and firmware components signed by Microsoft bootable
          includeMicrosoftKeys = true;
        };
      };

      # Provide sbctl status and sbctl verify for inspecting enrolment and signatures
      environment.systemPackages = [ pkgs.sbctl ];
    };

  ## Part 2. Boot test
  perSystem =
    { pkgs, ... }:
    {
      # Prove in a virtual machine that keys are generated, enrolled and enforced by Secure Boot firmware
      checks.secure-boot = pkgs.testers.runNixOSTest {
        name = "secure-boot";
        # Allow three software-emulated boots on machines where build users cannot use KVM
        globalTimeout = 40 * 60;

        nodes.machine =
          { lib, ... }:
          {
            # Combine lanzaboote's disk image with this repository's Secure Boot module
            imports = [
              "${harness}/lanzaboote.nix"
              topLevel.flake.modules.nixos.secure-boot
            ];

            # Supply the newer option expected by the harness while this repository still uses NixOS 26.05
            options.image.repart.enable = lib.mkOption {
              type = lib.types.bool;
              default = true;
            };

            config = {
              # Generate fresh keys during the test and keep them across its reboots
              lanzabooteTest = {
                keyFixture = false;
                persistentRoot = true;
              };
              # Give the firmware the TPM support used by this boot path
              virtualisation.tpm.enable = true;

              # Start Secure Boot-capable firmware in setup mode with no keys enrolled
              virtualisation.useSecureBoot = true;
            };
          };

        testScript =
          { nodes, ... }:
          (import "${harness}/image-helper.nix" { inherit (nodes) machine; })
          + ''
            ## Step 1. Generate keys on the first boot
            keys = "/var/lib/sbctl/keys"

            with subtest("1. First boot: Secure Boot is off and the machine generates its own keys"):
                t.assertIn("Secure Boot: disabled", machine.succeed("bootctl status"))
                machine.wait_for_unit("generate-sb-keys.service")
                machine.succeed(f"test -s {keys}/db/db.key")
                machine.wait_for_unit("prepare-sb-auto-enroll.service")
                print(machine.succeed("ls /boot/loader/keys/auto"))
                fingerprint = machine.succeed(f"sha256sum {keys}/db/db.key {keys}/PK/PK.key")

            ## Step 2. Check every file that the firmware starts
            # The boot menu and each generation image must be signed
            # Kernels under EFI/nixos are deliberately unsigned
            # The signed image checks their hashes in subtest 4
            with subtest("3. Everything the firmware starts is signed with these keys"):
                verify = machine.succeed("sbctl verify")
                print(verify)
                results = [line for line in verify.splitlines() if line.startswith(("✓", "✗"))]
                unsigned = [line for line in results if line.startswith("✗")]
                t.assertGreaterEqual(len(results) - len(unsigned), 3)
                for line in unsigned:
                    t.assertRegex(line, r"^✗ /boot/EFI/nixos/kernel-[^/]+\.efi is not signed$")

            ## Step 3. Reboot with the generated keys enrolled
            machine.reboot()

            with subtest("2. After a reboot the firmware enforces Secure Boot with these keys, and Microsoft's are enrolled"):
                t.assertIn("Secure Boot: enabled (user)", machine.succeed("bootctl status"))
                status = machine.succeed("sbctl status")
                print(status)
                t.assertIn("microsoft", status)

            ## Step 4. Prove later boots reuse the same keys
            with subtest("5. The keys are not generated again"):
                t.assertEqual(fingerprint, machine.succeed(f"sha256sum {keys}/db/db.key {keys}/PK/PK.key"))
                t.assertIn("start condition unmet", machine.fail("systemctl status generate-sb-keys.service"))
                t.assertIn("start condition unmet", machine.fail("systemctl status prepare-sb-auto-enroll.service"))

            ## Step 5. Prove a changed kernel cannot boot
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
