#!/usr/bin/env python3
"""Trigger inference image build for the current platform (PLATFORM=aws → CodeBuild)."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from env_helpers import WORKSPACE_ROOT, get_platform, infra_env_path, load_env


def _run_aws(no_cache: bool) -> None:
    infra = load_env(infra_env_path("aws"))
    project = infra.get("CODEBUILD_PROJECT_NAME")
    region = infra.get("REGION")
    if not project or not region:
        print(
            "Error: CODEBUILD_PROJECT_NAME and REGION required in infra .env. "
            "Run: nx run aws-infra:terraform-output",
            file=sys.stderr,
        )
        sys.exit(1)
    cmd = [
        "aws",
        "codebuild",
        "start-build",
        "--project-name",
        project,
        "--region",
        region,
    ]
    if no_cache:
        cmd.extend([
            "--environment-variables-override",
            "name=DOCKER_BUILD_EXTRA_ARGS,value=--no-cache,type=PLAINTEXT",
        ])
    env = {**os.environ, **{k: v for k, v in infra.items() if v is not None}}
    subprocess.run(cmd, cwd=str(WORKSPACE_ROOT), env=env, check=True)
    print("CodeBuild started. Check AWS console for build status.")


def _run_gcp() -> None:
    print("Error: GCP inference build is not implemented yet.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger inference image build (platform from PLATFORM).")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Pass --no-cache to Docker build (e.g. for FFmpeg/PyAV rebuild).",
    )
    args = parser.parse_args()

    platform = get_platform()
    if platform == "aws":
        _run_aws(no_cache=args.no_cache)
    elif platform == "gcp":
        _run_gcp()
    else:
        print(f"Error: Unsupported PLATFORM={platform}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
