# Desktop audio
#
# What it is    PipeWire audio with compatibility for ALSA, 32-bit applications and PulseAudio clients
# Who uses it   A NixOS host through nixos.desktop; nixos.desktop-kde imports that module
# A host adds   Nothing; desktop applications discover the shared audio service automatically
# Protected     No: this is a replaceable desktop service rather than an access or recovery safeguard
{
  flake.modules.nixos.desktop = {
    # Let the audio service request safe real-time scheduling for reliable playback
    security.rtkit.enable = true;

    services = {
      pipewire = {
        # Use PipeWire as the desktop's audio service
        enable = true;

        # Keep native ALSA applications working through PipeWire
        alsa.enable = true;

        # Keep older 32-bit applications able to play sound
        alsa.support32Bit = true;

        # Keep applications written for PulseAudio working through PipeWire
        pulse.enable = true;
      };
    };
  };
}
