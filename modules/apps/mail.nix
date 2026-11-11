# Thunderbird with telemetry off; users opt in by importing homeManager.mail
{
  flake.modules.homeManager.mail = {
    programs.thunderbird = {
      enable = true;

      # One profile without accounts; accounts are set up by hand in Thunderbird
      profiles.default = {
        isDefault = true;

        # Written to user.js, which Thunderbird re-applies at every start
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
