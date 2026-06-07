#!/usr/bin/env python3
"""
LLM Council prerequisite checker and setup script.

Modes:
    --check       Fast check only (boto3 importable? AWS credentials valid?)
                  Returns JSON: {"ok": bool, "issues": [...], "cache_valid": bool}

    --check-full  Full check including per-model Bedrock access (may take a few seconds).
                  Writes a cache file so subsequent --check calls skip the slow part.

    --fix         Interactive setup: installs missing deps, configures AWS SSO,
                  enables Bedrock model access. Meant to be driven by a human.

    --status      Print a human-readable status table.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CACHE_FILE = Path.home() / ".claude" / "dsvellal-council-setup-cache.json"
CACHE_TTL_SECONDS = 3600  # 1 hour

# Models that the workflow uses — must stay in sync with dsvellal-llm-council.js
REQUIRED_CLAUDE_MODELS = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-opus-4-8",  # Chairman
]
REQUIRED_BEDROCK_MODELS = [
    "meta.llama3-70b-instruct-v1:0",
    "mistral.mistral-large-2402-v1:0",
]

BEDROCK_CONSOLE_URL = (
    "https://console.aws.amazon.com/bedrock/home#/modelaccess"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, capture=True, check=False):
    """Run a shell command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=capture, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def load_cache():
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text())
        if time.time() - data.get("timestamp", 0) < CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def save_cache(data):
    data["timestamp"] = time.time()
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2))


def detect_region():
    """Return the active AWS region, falling back to us-east-1."""
    # 1. Environment variable
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
    if region:
        return region
    # 2. AWS CLI config
    rc, out, _ = run("aws configure get region")
    if rc == 0 and out:
        return out
    # 3. Active SSO profile region
    rc, out, _ = run("aws configure get region --profile default")
    if rc == 0 and out:
        return out
    return "us-east-1"


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_python():
    """Verify Python 3.8+ is available."""
    if sys.version_info < (3, 8):
        return False, f"Python {sys.version} is too old (need 3.8+)"
    return True, f"Python {sys.version.split()[0]}"


def check_boto3():
    """Verify boto3 is importable."""
    try:
        import boto3  # noqa: F401
        import botocore  # noqa: F401
        return True, "boto3 installed"
    except ImportError:
        return False, "boto3 not installed"


def check_aws_cli():
    """Verify AWS CLI v2 is on PATH."""
    if shutil.which("aws") is None:
        return False, "aws CLI not found"
    rc, out, _ = run("aws --version")
    return rc == 0, out.split()[0] if rc == 0 else "aws CLI error"


def check_aws_credentials():
    """Verify active AWS credentials via sts get-caller-identity."""
    rc, out, err = run("aws sts get-caller-identity --output json")
    if rc != 0:
        return False, f"No valid credentials: {err}"
    try:
        identity = json.loads(out)
        return True, f"Account {identity.get('Account')} / {identity.get('Arn', '').split('/')[-1]}"
    except Exception:
        return False, "Could not parse STS response"


def check_bedrock_model(model_id, region):
    """Check if a specific Bedrock model is accessible."""
    rc, out, err = run(
        f"aws bedrock get-foundation-model --model-identifier {model_id} "
        f"--region {region} --output json"
    )
    if rc != 0:
        return False, err
    try:
        data = json.loads(out)
        status = data.get("modelDetails", {}).get("modelLifecycle", {}).get("status", "UNKNOWN")
        return True, status
    except Exception:
        return True, "accessible"


def check_bedrock_access(region):
    """Check access to all required Bedrock models."""
    results = {}
    for model_id in REQUIRED_BEDROCK_MODELS:
        ok, msg = check_bedrock_model(model_id, region)
        results[model_id] = {"ok": ok, "msg": msg}
    return results


# ---------------------------------------------------------------------------
# Fix functions
# ---------------------------------------------------------------------------

def install_boto3():
    """Install boto3 via pip."""
    print("\n[SETUP] Installing boto3...")
    rc, out, err = run(
        f"{sys.executable} -m pip install boto3 --quiet", capture=False
    )
    if rc != 0:
        print(f"  ERROR: pip install failed: {err}")
        return False
    print("  boto3 installed successfully.")
    return True


def configure_aws_sso(region):
    """
    Guide the user through aws configure sso interactively.
    This must be run in a real terminal — we print instructions.
    """
    print("\n" + "=" * 60)
    print("AWS SSO CONFIGURATION")
    print("=" * 60)
    print("""
You need to configure AWS credentials via SSO (IAM Identity Center).
This opens a browser window to authenticate.

Step-by-step:

  1. Run this command in your terminal:

       aws configure sso

  2. When prompted for "SSO session name", enter a short name like:
       my-sso

  3. "SSO start URL" — enter your company's SSO URL, e.g.:
       https://my-company.awsapps.com/start

     If you don't know it, ask your AWS admin, or check:
       https://console.aws.amazon.com/iam/home#/identity-center

  4. "SSO region" — enter the region where IAM Identity Center is set up
     (usually us-east-1 or your org's primary region).

  5. A browser window will open. Log in with your corporate/SSO credentials.

  6. Back in the terminal, select the AWS account and role you want to use.

  7. For "CLI default client Region", enter:
       {region}

  8. For "CLI default output format", press Enter to accept "json".

  9. For "CLI profile name", enter:
       default

  10. Test it worked:
        aws sts get-caller-identity

After completing the above, re-run:
  /dsvellal-llm-council-setup

""".format(region=region))


def enable_bedrock_model(model_id, region):
    """
    Attempt to enable a Bedrock model via the AWS CLI.
    Falls back to manual Console instructions if the API call isn't available.
    """
    print(f"\n[SETUP] Enabling Bedrock model: {model_id}")

    # Try the batch model access API (available in some regions/accounts)
    payload = json.dumps({
        "modelAccessUpdates": [
            {"modelId": model_id, "resourceType": "FOUNDATION_MODEL"}
        ]
    })
    payload_escaped = payload.replace('"', '\\"')

    rc, out, err = run(
        f"aws bedrock put-model-invocation-logging-configuration "
        f"--region {region} 2>&1 | head -1"
    )

    # Try direct model access request
    rc2, out2, err2 = run(
        f"aws bedrock create-model-invocation-logging-configuration "
        f"--region {region} 2>&1 | head -1"
    )

    # The dedicated endpoint for model access is:
    # aws bedrock put-model-access (not available in all SDK versions)
    rc3, out3, err3 = run(
        f"aws bedrock request-model-access "
        f"--model-ids {model_id} "
        f"--region {region} --output json 2>&1"
    )

    if rc3 == 0:
        print(f"  Access requested for {model_id}. It may take a few minutes to activate.")
        return True

    # Fall back to manual instructions
    print(f"""
  Could not automatically enable {model_id} via CLI.
  (The 'request-model-access' API may not be available in your CLI version or region.)

  To enable manually:

    1. Open the Bedrock Model Access console:
       {BEDROCK_CONSOLE_URL}?region={region}

    2. Click "Modify model access" (top right).

    3. Find and tick the checkbox for:
         {model_id}

    4. Click "Next" → "Submit".

    5. Wait ~1 minute for access to activate.

    6. Re-run: /dsvellal-llm-council-setup
""")
    return False


# ---------------------------------------------------------------------------
# Main modes
# ---------------------------------------------------------------------------

def mode_check(full=False):
    """
    Fast (or full) check. Returns a JSON result dict.
    The workflow calls this and parses the JSON.
    """
    issues = []
    warnings = []

    # --- Fast checks (always run) ---
    ok_py, msg_py = check_python()
    if not ok_py:
        issues.append(f"Python: {msg_py}")

    ok_boto3, msg_boto3 = check_boto3()
    if not ok_boto3:
        issues.append("boto3 not installed — run /dsvellal-llm-council-setup")

    ok_cli, msg_cli = check_aws_cli()
    if not ok_cli:
        issues.append("AWS CLI not found — install from https://aws.amazon.com/cli/")

    ok_creds, msg_creds = check_aws_credentials()
    if not ok_creds:
        issues.append(f"AWS credentials: {msg_creds} — run /dsvellal-llm-council-setup")

    if issues:
        result = {"ok": False, "issues": issues, "warnings": warnings, "cache_valid": False}
        print(json.dumps(result))
        return result

    # --- Slow checks (from cache unless full=True) ---
    region = detect_region()
    cache = load_cache() if not full else None

    if cache and not full:
        result = {
            "ok": True,
            "issues": [],
            "warnings": warnings,
            "cache_valid": True,
            "region": cache.get("region", region),
            "identity": cache.get("identity", "cached"),
            "models": cache.get("models", {}),
        }
        print(json.dumps(result))
        return result

    # Run full model checks
    model_results = check_bedrock_access(region)
    failed_models = [m for m, r in model_results.items() if not r["ok"]]
    if failed_models:
        for m in failed_models:
            warnings.append(
                f"Bedrock model not accessible: {m} — run /dsvellal-llm-council-setup"
            )

    _, identity_out, _ = run("aws sts get-caller-identity --output json")
    try:
        identity = json.loads(identity_out).get("Arn", "").split("/")[-1]
    except Exception:
        identity = "unknown"

    result = {
        "ok": True,
        "issues": [],
        "warnings": warnings,
        "cache_valid": False,
        "region": region,
        "identity": identity,
        "models": model_results,
    }
    save_cache(result)
    print(json.dumps(result))
    return result


def mode_fix():
    """Interactive setup flow — meant to be driven by a human in a terminal."""
    print("\n" + "=" * 60)
    print("LLM COUNCIL — SETUP")
    print("=" * 60)

    region = detect_region()
    print(f"\nDetected AWS region: {region}")

    # Step 1: Python
    ok, msg = check_python()
    print(f"\n[1/5] Python ........... {'OK' if ok else 'FAIL'} ({msg})")
    if not ok:
        print("  Please upgrade Python to 3.8+ and re-run this script.")
        sys.exit(1)

    # Step 2: boto3
    ok, msg = check_boto3()
    print(f"[2/5] boto3 ............ {'OK' if ok else 'MISSING'} ({msg})")
    if not ok:
        installed = install_boto3()
        if not installed:
            print("  Please install manually: pip install boto3")
            sys.exit(1)

    # Step 3: AWS CLI
    ok, msg = check_aws_cli()
    print(f"[3/5] AWS CLI .......... {'OK' if ok else 'MISSING'} ({msg})")
    if not ok:
        print("""
  AWS CLI v2 is required. To install:

    macOS:
      brew install awscli
      — or —
      curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o awscliv2.pkg
      sudo installer -pkg awscliv2.pkg -target /

    Linux:
      curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
      unzip awscliv2.zip && sudo ./aws/install

  After installing, re-run: /dsvellal-llm-council-setup
""")
        sys.exit(1)

    # Step 4: AWS credentials
    ok, msg = check_aws_credentials()
    print(f"[4/5] AWS credentials .. {'OK' if ok else 'MISSING'} ({msg})")
    if not ok:
        configure_aws_sso(region)
        sys.exit(0)  # User must complete SSO and re-run

    # Step 5: Bedrock model access
    print(f"[5/5] Bedrock models ... checking in region {region}...")
    model_results = check_bedrock_access(region)
    all_ok = True
    for model_id, r in model_results.items():
        status = "OK" if r["ok"] else "NOT ENABLED"
        print(f"      {model_id:50s} {status}")
        if not r["ok"]:
            all_ok = False

    if not all_ok:
        print("\n  Some models need to be enabled. Attempting to enable via AWS CLI...")
        for model_id, r in model_results.items():
            if not r["ok"]:
                enable_bedrock_model(model_id, region)
    else:
        print("\n  All models accessible.")

    # Final summary
    print("\n" + "=" * 60)
    if all_ok:
        print("SETUP COMPLETE — /dsvellal-llm-council is ready to use.")
    else:
        print("SETUP PARTIALLY COMPLETE")
        print("Follow the manual steps above, then re-run: /dsvellal-llm-council-setup")
    print("=" * 60 + "\n")

    # Invalidate cache so next --check-full re-validates
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()


def mode_status():
    """Print a human-readable status table."""
    region = detect_region()
    checks = [
        ("Python",          check_python()),
        ("boto3",           check_boto3()),
        ("AWS CLI",         check_aws_cli()),
        ("AWS credentials", check_aws_credentials()),
    ]
    print("\nLLM Council — Prerequisite Status")
    print("-" * 50)
    for name, (ok, msg) in checks:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol}  {name:25s} {msg}")

    print(f"\n  Region: {region}")
    print("\n  Bedrock model access:")
    model_results = check_bedrock_access(region)
    for model_id, r in model_results.items():
        symbol = "✓" if r["ok"] else "✗"
        print(f"  {symbol}  {model_id:50s} {r['msg']}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check",      action="store_true", help="Fast check, JSON output")
    parser.add_argument("--check-full", action="store_true", help="Full check incl. model access, JSON output")
    parser.add_argument("--fix",        action="store_true", help="Interactive setup")
    parser.add_argument("--status",     action="store_true", help="Human-readable status")
    args = parser.parse_args()

    if args.check:
        mode_check(full=False)
    elif args.check_full:
        mode_check(full=True)
    elif args.fix:
        mode_fix()
    elif args.status:
        mode_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
