# stereocrafter-sagemaker

SageMaker inference container using **iw3** ([nunif](https://github.com/nagadomi/nunif)): converts 2D video segments to stereoscopic 3D (side-by-side or anaglyph).

## Contract

- **GET /ping** — returns 200 OK (SageMaker health check).
- **POST /invocations** — body: JSON `{"s3_input_uri": "...", "s3_output_uri": "...", "mode": "anaglyph"|"sbs"}`. The `mode` is optional and defaults to `"anaglyph"`. The handler downloads the segment from S3, runs **iw3** (2D→stereo), and uploads the result to `s3_output_uri`.

## Pipeline

The container runs **iw3** from the [nunif](https://github.com/nagadomi/nunif) repo:

- **Input:** Segment video from S3 (e.g. from media-worker chunking).
- **iw3:** Depth estimation (ZoeDepth / Depth-Anything, etc.) + stereo generation (SBS or anaglyph). Uses `--scene-detect` and `--ema-normalize` for video; for anaglyph adds `--convergence 0.5 --divergence 2.0 --pix-fmt yuv444p`.
- **Output:** Single stereo MP4 written to the given `s3_output_uri`.

Pre-trained models (ZoeDepth, Depth-Anything, row_flow, etc.) are **baked into the image** at build time via `python -m iw3.download_models`; no network or Secrets Manager at startup.

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

- **sagemaker-build**: CodeBuild clones the public repo, runs `docker build`, and pushes to ECR. No local Docker build required.
- **sagemaker-deploy**: Creates a new SageMaker model and endpoint config pointing at the ECR image (`:latest`), then updates the endpoint. The config includes async inference (same as Terraform) so the update is accepted. Requires `terraform-output` so `.env` includes `SAGEMAKER_ENDPOINT_NAME`, `SAGEMAKER_ENDPOINT_ROLE_ARN`, `SAGEMAKER_INSTANCE_TYPE`, `SAGEMAKER_INSTANCE_COUNT`, `ECR_STEREOCRAFTER_SAGEMAKER_URL`, `REGION`, and `OUTPUT_BUCKET_NAME` (or `output_bucket_name`) for async response paths.

Terraform expects the image at the ECR repository URL with tag from `ecs_image_tag` (e.g. `latest`). When Terraform is set to `inference_backend=http`, the video-worker uses `inference_http_url` (you run the inference service yourself).

## Environment variables

| Variable           | Description |
|--------------------|-------------|
| `IW3_LOW_VRAM`     | Optional. Set to `1` to pass `--low-vram` to iw3 (e.g. for smaller GPU instances like g5.xlarge). |
| `NUNIF_HOME`       | Set in the image to `/opt/nunif_data` (where models are stored). |

No Hugging Face token is required; models are baked in at build time.

## Optional iw3 tuning (for future use)

Additional iw3 options can be useful; they are documented in [docs/RUNBOOKS.md](../../docs/RUNBOOKS.md#optional-iw3-tuning-sagemaker-inference-container) and can be wired in via env or request body later:

| Goal                  | iw3 option / env              | Notes |
|-----------------------|-------------------------------|--------|
| **Reduce VRAM**       | `IW3_LOW_VRAM=1`              | Supported now. |
| **Preserve 60fps**    | `--max-fps 128`               | Default is 30fps; 60fps increases processing time. |
| **Smaller output**     | `--preset medium`, `--video-codec libx265` | Lower bitrate / file size. |
| **Older GPUs**        | `--disable-amp`                | Disable FP16 on pre–GeForce 20 GPUs. |

To add these, extend `serve.py` to read env vars (e.g. `IW3_MAX_FPS`, `IW3_PRESET`) and append the corresponding flags to the iw3 CLI.
