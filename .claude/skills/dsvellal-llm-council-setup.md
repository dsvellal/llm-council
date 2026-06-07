# dsvellal LLM Council Setup

Configure prerequisites for the LLM Council: installs boto3, sets up AWS SSO credentials, and enables Bedrock model access.

## Usage

```
/dsvellal-llm-council-setup
```

Run this before using `/dsvellal-llm-council` for the first time, or whenever you get a credentials or model-access error.

## What it checks and fixes

1. **Python 3.8+** — required to run the Bedrock query helper
2. **boto3** — auto-installs via pip if missing
3. **AWS CLI v2** — checks if installed; provides install instructions if not
4. **AWS credentials** — validates via `sts get-caller-identity`; walks you through SSO setup if missing
5. **Bedrock model access** — checks each council model; attempts to enable via AWS CLI, falls back to Console instructions

## Instructions

<skill>

When the user invokes `/dsvellal-llm-council-setup`:

1. First run a status check so the user can see what's currently passing and what needs fixing:

   Run this command and show the output to the user:
   ```
   python3 ~/.claude/scripts/dsvellal_council_setup.py --status
   ```

2. Then run the interactive fix in a Bash tool call (capture=false so output streams live):
   ```
   python3 ~/.claude/scripts/dsvellal_council_setup.py --fix
   ```

3. Read the output carefully:

   a. If the script exits with instructions telling the user to run a command themselves
      (e.g. `aws configure sso`), show those instructions clearly formatted and tell the
      user: "Please follow the steps above in your terminal. Once done, run `/dsvellal-llm-council-setup`
      again to continue."

   b. If the script prints a Console URL for manual model access, present it as a clickable
      link and give the numbered steps clearly.

   c. If the script prints "SETUP COMPLETE", confirm to the user that `/dsvellal-llm-council` is
      ready to use and suggest a test question.

4. After any user action (they ran `aws configure sso`, they enabled a model), re-run
   the status check to confirm things are now green:
   ```
   python3 ~/.claude/scripts/dsvellal_council_setup.py --status
   ```

5. If all checks pass, run a final full validation to warm the model cache:
   ```
   python3 ~/.claude/scripts/dsvellal_council_setup.py --check-full
   ```
   Tell the user this caches model access checks for 1 hour so `/dsvellal-llm-council` starts faster.

</skill>
