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
# Deploy: triggers AWS CodeBuild to clone the repo, build the image, and push to ECR
# Requires aws-infra:terraform-output (writes .env with CODEBUILD_PROJECT_NAME, REGION)
nx run stereocrafter-sagemaker:deploy
```

CodeBuild clones the public repo, runs `docker build`, and pushes to ECR. No local Docker build needed.

**Build time (from scratch):** ~7–8 minutes on CodeBuild `BUILD_GENERAL1_LARGE` (clone ~3s, base image ~70s, apt ~15s, StereoCrafter deps ~82s, Forward-Warp ~1min, push ~4min). Subsequent builds benefit from Docker layer cache if layers are unchanged.

For local build (requires Docker and ~10GB+ for CUDA base + StereoCrafter):
```bash
nx run stereocrafter-sagemaker:build
# Then manually: docker tag ... && docker push ... (or use ecr-login + push)
```

Terraform expects the image at the ECR repository URL with tag from `ecs_image_tag` (e.g. `latest`). After deploying, update the SageMaker endpoint (re-deploy or create new endpoint config) so it uses the new image.

## Environment variables (injected by SageMaker/Terraform)

| Variable      | Description |
|---------------|-------------|
| `HF_TOKEN_ARN` | ARN of the Secrets Manager secret containing the Hugging Face token (for gated model download at startup). |
| `WEIGHTS_DIR` | Directory for downloaded weights (default `/opt/ml/model/weights`). |
