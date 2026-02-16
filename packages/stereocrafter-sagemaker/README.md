# stereocrafter-sagemaker

SageMaker inference container for **StereoCrafter**: converts 2D video segments to stereoscopic 3D.

## Contract

- **GET /ping** — returns 200 OK (SageMaker health check).
- **POST /invocations** — body: JSON `{"s3_input_uri": "...", "s3_output_uri": "...", "mode": "anaglyph"|"sbs"}`. The `mode` is optional and defaults to `"anaglyph"`. The handler reads the segment from S3, runs the two-stage pipeline (depth splatting → inpainting), and writes the result in the requested format to `s3_output_uri`.

## Pipeline

1. **Depth splatting** (`depth_splatting_inference.py`): DepthCrafter + SVD → splatting result (depth grid).
2. **Inpainting** (`inpainting_inference.py`): StereoCrafter + SVD → final stereo. Produces both side-by-side and anaglyph; the handler selects the file matching the requested `mode` and uploads it to S3.

## Weights at startup

Model weights are **not** baked into the image. The container reads **`HF_TOKEN_ARN`** from the environment (injected by Terraform from Secrets Manager). At startup it:

1. Calls `secretsmanager:GetSecretValue` with that ARN to get the Hugging Face token.
2. Downloads the three weight sets from Hugging Face into `WEIGHTS_DIR` (default `/opt/ml/model/weights`):
   - `stabilityai/stable-video-diffusion-img2vid-xt-1-1`
   - `tencent/DepthCrafter`
   - `TencentARC/StereoCrafter`

If `HF_TOKEN_ARN` is not set, the download is skipped and the server still starts (inference will fail until weights are present).

## Build and deploy

From the repo root:

```bash
# 1. Build: triggers AWS CodeBuild to clone the repo, build the image, and push to ECR
# Requires aws-infra:terraform-output (writes .env with CODEBUILD_PROJECT_NAME, REGION, etc.)
nx run stereocrafter-sagemaker:sagemaker-build

# 2. Deploy: update the SageMaker endpoint to use the new image in ECR
# (Creates a new model and endpoint config, then updates the endpoint so it pulls the latest image.)
nx run stereocrafter-sagemaker:sagemaker-deploy
```

- **sagemaker-build**: CodeBuild clones the public repo, runs `docker build`, and pushes to ECR. No local Docker build.
- **sagemaker-deploy**: Creates a new SageMaker model and endpoint config pointing at the ECR image (`:latest`), then updates the endpoint so new instances use the new image. Requires `terraform-output` to have been run so `.env` includes `SAGEMAKER_ENDPOINT_NAME`, `SAGEMAKER_ENDPOINT_ROLE_ARN`, `SAGEMAKER_INSTANCE_TYPE`, `SAGEMAKER_INSTANCE_COUNT`, `ECR_STEREOCRAFTER_SAGEMAKER_URL`, `HF_TOKEN_SECRET_ARN`, `REGION`.

**Build time (from scratch):** ~7–8 minutes on CodeBuild `BUILD_GENERAL1_LARGE` (clone ~3s, base image ~70s, apt ~15s, StereoCrafter deps ~82s, Forward-Warp ~1min, push ~4min). Subsequent builds benefit from Docker layer cache if layers are unchanged.

Terraform expects the image at the ECR repository URL with tag from `ecs_image_tag` (e.g. `latest`). Run `sagemaker-deploy` after `sagemaker-build` (or after pushing a new image to ECR) to roll out the new image to the SageMaker endpoint.

**Docker image:** Includes `libgl1-mesa-glx` and `libglib2.0-0` so `cv2` (opencv) in the StereoCrafter scripts can load without a display.

### HTTP backend (EC2 for dev/testing)

When Terraform is set to `inference_backend=http`, the video-worker calls an HTTP URL instead of SageMaker. You can run the same container on a GPU EC2 for faster iteration:

- **stereocrafter-ec2-deploy**: Updates the inference EC2 with the latest image from ECR via SSM (no SageMaker endpoint update). Requires `inference_backend=http` and `inference_http_url` empty (so Terraform creates the EC2). Run after `sagemaker-build` to roll the EC2 to the new image.

**Getting your latest code onto EC2:** `sagemaker-build` runs **AWS CodeBuild**, which **clones the Git repo** (e.g. `codebuild_stereocrafter_repo_url` in Terraform). So the image that gets built contains whatever is on that **remote** repo (e.g. `origin/main`). **Push your commits** (e.g. `git push`) before running `sagemaker-build`, then wait for the build to finish, then run **stereocrafter-ec2-deploy** so the EC2 pulls the new image and restarts the container. **terraform-apply** only updates infrastructure (volumes, IAM, etc.); it does not build the image or update the running container.

## Environment variables (injected by SageMaker/Terraform)

| Variable      | Description |
|---------------|-------------|
| `HF_TOKEN_ARN` | ARN of the Secrets Manager secret containing the Hugging Face token (for gated model download at startup). |
| `WEIGHTS_DIR` | Directory for downloaded weights (default `/opt/ml/model/weights`). |
