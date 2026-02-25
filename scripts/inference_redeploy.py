#!/usr/bin/env python3
"""Redeploy inference image to the platform endpoint (PLATFORM=aws → SageMaker)."""

import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from env_helpers import WORKSPACE_ROOT, get_platform, infra_env_path


def _run_aws() -> None:
    env_path = infra_env_path("aws")
    if not env_path.exists():
        print(
            f"Error: Env file not found: {env_path}. Run: nx run aws-infra:terraform-output",
            file=sys.stderr,
        )
        sys.exit(1)
    deploy_script = WORKSPACE_ROOT / "packages" / "stereo-inference" / "scripts" / "deploy-sagemaker.sh"
    subprocess.run(
        ["bash", str(deploy_script), str(env_path)],
        cwd=str(WORKSPACE_ROOT),
        check=True,
    )


def _run_gcp() -> None:
    print("Error: GCP inference redeploy is not implemented yet.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    platform = get_platform()
    if platform == "aws":
        _run_aws()
    elif platform == "gcp":
        _run_gcp()
    else:
        print(f"Error: Unsupported PLATFORM={platform}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
