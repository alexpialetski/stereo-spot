#!/usr/bin/env python3
"""Import ALB cert and key into ACM and set TF_VAR_load_balancer_certificate_id in root .env. AWS only."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from env_helpers import WORKSPACE_ROOT, get_platform, infra_env_path, load_env, set_env_var


def _run_aws(cert_path: Path, key_path: Path) -> str:
    infra = load_env(infra_env_path("aws"))
    region = infra.get("AWS_REGION") or os.environ.get("AWS_REGION") or "us-east-1"

    result = subprocess.run(
        [
            "aws", "acm", "import-certificate",
            "--certificate", f"fileb://{cert_path.resolve()}",
            "--private-key", f"fileb://{key_path.resolve()}",
            "--region", region,
        ],
        capture_output=True,
        text=True,
        cwd=str(WORKSPACE_ROOT),
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    out = json.loads(result.stdout)
    arn = out.get("CertificateArn")
    if not arn:
        print("Error: No CertificateArn in aws acm import-certificate output.", file=sys.stderr)
        sys.exit(1)
    return arn


def _run_gcp(cert_path: Path, key_path: Path) -> None:
    print("Error: GCP cloud is not supported for now.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import ALB certificate into ACM and update root .env for Terraform.")
    parser.add_argument(
        "--cert-file",
        type=Path,
        default=WORKSPACE_ROOT / "alb-certificate.pem",
        help="Path to certificate PEM (default: alb-certificate.pem at repo root)",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=WORKSPACE_ROOT / "alb-private-key.pem",
        help="Path to private key PEM (default: alb-private-key.pem at repo root)",
    )
    args = parser.parse_args()

    platform = get_platform()
    cert_path = args.cert_file if args.cert_file.is_absolute() else WORKSPACE_ROOT / args.cert_file
    key_path = args.key_file if args.key_file.is_absolute() else WORKSPACE_ROOT / args.key_file
    if not cert_path.exists():
        print(f"Error: Certificate file not found: {cert_path}", file=sys.stderr)
        sys.exit(1)
    if not key_path.exists():
        print(f"Error: Private key file not found: {key_path}", file=sys.stderr)
        sys.exit(1)

    if platform == "aws":
        certificate_id = _run_aws(cert_path, key_path)
    elif platform == "gcp":
        _run_gcp(cert_path, key_path)
    else:
        print(f"Error: Unsupported PLATFORM={platform}.", file=sys.stderr)
        sys.exit(1)

    root_env = WORKSPACE_ROOT / ".env"
    set_env_var(root_env, "TF_VAR_load_balancer_certificate_id", certificate_id)
    print(f"Imported certificate into ACM: {certificate_id}")
    print("Set TF_VAR_load_balancer_certificate_id in root .env. Run terraform apply to attach the cert to the ALB.")


if __name__ == "__main__":
    main()
