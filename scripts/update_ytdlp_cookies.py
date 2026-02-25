#!/usr/bin/env python3
"""Push ytdlp cookies file to Secrets Manager and set TF_VAR_enable_youtube_ingest=true in root .env. Set PLATFORM=aws."""

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from env_helpers import WORKSPACE_ROOT, get_platform, infra_env_path, load_env, set_env_var


def _run_aws(cookies_data: bytes) -> None:
    infra = load_env(infra_env_path("aws"))
    secret_arn = infra.get("YTDLP_COOKIES_SECRET_ARN")
    if not secret_arn:
        print("Error: YTDLP_COOKIES_SECRET_ARN not in infra .env. Set TF_VAR_enable_youtube_ingest=true and apply first.", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({"cookies_base64": base64.b64encode(cookies_data).decode("ascii")})
    subprocess.run(
        [
            "aws", "secretsmanager", "put-secret-value",
            "--secret-id", secret_arn,
            "--secret-string", payload,
        ],
        check=True,
        cwd=str(WORKSPACE_ROOT),
    )
    print("ytdlp cookies updated in Secrets Manager.")


def _run_gcp(cookies_data: bytes) -> None:
    print("Error: GCP cloud is not supported for now.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Push ytdlp cookies to Secrets Manager.")
    parser.add_argument(
        "--cookies-file",
        type=Path,
        default=WORKSPACE_ROOT / "ytdlp_cookies.txt",
        help="Path to Netscape-format cookies file (default: ytdlp_cookies.txt at repo root)",
    )
    args = parser.parse_args()

    platform = get_platform()
    cookies_path = args.cookies_file if args.cookies_file.is_absolute() else WORKSPACE_ROOT / args.cookies_file
    if not cookies_path.exists():
        print(f"Error: Cookies file not found: {cookies_path}", file=sys.stderr)
        sys.exit(1)
    cookies_data = cookies_path.read_bytes()

    if platform == "aws":
        _run_aws(cookies_data)
    elif platform == "gcp":
        _run_gcp(cookies_data)
    else:
        print(f"Error: Unsupported PLATFORM={platform}.", file=sys.stderr)
        sys.exit(1)

    root_env = WORKSPACE_ROOT / ".env"
    set_env_var(root_env, "TF_VAR_enable_youtube_ingest", "true")
    print("Set TF_VAR_enable_youtube_ingest=true in root .env. Run terraform apply to enable the feature.")


if __name__ == "__main__":
    main()
