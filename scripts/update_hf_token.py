#!/usr/bin/env python3
"""Push HF_TOKEN from root .env (or env) to Secrets Manager. Set PLATFORM=aws."""

import json
import os
import subprocess
import sys
from pathlib import Path

# Allow running from repo root; script may live in scripts/
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from env_helpers import WORKSPACE_ROOT, get_platform, infra_env_path, load_env


def _run_aws(token: str) -> None:
    infra = load_env(infra_env_path("aws"))
    secret_arn = infra.get("HF_TOKEN_SECRET_ARN")
    if not secret_arn:
        print("Error: HF_TOKEN_SECRET_ARN not in infra .env.", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({"token": token})
    subprocess.run(
        [
            "aws", "secretsmanager", "put-secret-value",
            "--secret-id", secret_arn,
            "--secret-string", payload,
        ],
        check=True,
        cwd=str(WORKSPACE_ROOT),
    )
    print("HF token updated in Secrets Manager.")


def _run_gcp(token: str) -> None:
    print("Error: GCP cloud is not supported for now.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    platform = get_platform()
    root_env = WORKSPACE_ROOT / ".env"
    root_vars = load_env(root_env) if root_env.exists() else {}
    token = os.environ.get("HF_TOKEN") or root_vars.get("HF_TOKEN")
    if not token:
        print("Error: Set HF_TOKEN in root .env or in the environment.", file=sys.stderr)
        sys.exit(1)

    if platform == "aws":
        _run_aws(token)
    elif platform == "gcp":
        _run_gcp(token)
    else:
        print(f"Error: Unsupported PLATFORM={platform}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
