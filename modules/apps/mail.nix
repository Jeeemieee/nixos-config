# Email client
#
# What it is    Thunderbird with one local profile and data reporting disabled
# Who uses it   A Home Manager user by importing homeManager.mail; the workstation account imports it
# A user adds   Email accounts by hand in Thunderbird because account details are not stored here
# Protected     No: this module only configures a user application
{
  flake.modules.homeManager.mail = {
    programs.thunderbird = {
      # Install Thunderbird and let Home Manager maintain its profile
      enable = true;

      # Keep one default profile without storing private account details in this repository
      profiles.default = {
        isDefault = true;

        # Write the privacy choices to user.js so Thunderbird reapplies them at every start
        settings = {
          "toolkit.telemetry.enabled" = false;
          "datareporting.healthreport.uploadEnabled" = false;
          "datareporting.policy.dataSubmissionEnabled" = false;
          "app.shield.optoutstudies.enabled" = false;
        };
      };
    };
  };
}
