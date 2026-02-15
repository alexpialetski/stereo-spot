# stereocrafter-sagemaker

SageMaker inference container for **StereoCrafter**: converts 2D video segments to stereoscopic 3D.

## Contract

- **GET /ping** — returns 200 OK (SageMaker health check).
- **POST /invocations** — body: JSON `{"s3_input_uri": "...", "s3_output_uri": "..."}`. The handler reads the segment from S3, runs the two-stage pipeline (depth splatting → inpainting), and **writes the result to `s3_output_uri`**. No response body required beyond success/failure.

## Weights at startup

Model weights are **not** baked into the image. The container reads **`HF_TOKEN_ARN`** from the environment (injected by Terraform from Secrets Manager). At startup it should:

1. Call `secretsmanager:GetSecretValue` with that ARN to get the Hugging Face token.
2. Download the three weight sets from Hugging Face into a local directory (e.g. `/opt/ml/model/weights`):
   - Stable Video Diffusion (img2vid)
   - DepthCrafter
   - StereoCrafter

See [StereoCrafter](https://github.com/TencentARC/StereoCrafter) for the exact clone URLs and layout.

## Current implementation

- **Stub:** The image built from this package currently uses a **stub** handler that copies the input segment to the output S3 URI. This validates the SageMaker contract and the video-worker → endpoint → S3 flow.
- **Production:** Replace the stub in `serve.py` with the real StereoCrafter two-stage pipeline (clone the repo in the Dockerfile, install Forward-Warp, and call `depth_splatting_inference.py` and `inpainting_inference.py` from the handler).

## Build and push

From the repo root:

```bash
# Build (uses Dockerfile in this package)
nx run stereocrafter-sagemaker:build

# Push to ECR (after aws-infra:terraform-output and ecr-login)
nx run stereocrafter-sagemaker:deploy
```

Terraform expects the image at the ECR repository URL with tag from `ecs_image_tag` (e.g. `latest`). After pushing, update the SageMaker endpoint (re-deploy or create new endpoint config) so it uses the new image.

## Environment variables (injected by SageMaker/Terraform)

| Variable      | Description |
|---------------|-------------|
| `HF_TOKEN_ARN` | ARN of the Secrets Manager secret containing the Hugging Face token (for gated model download at startup). |

## Production Dockerfile notes

For the real StereoCrafter pipeline:

1. Base image: CUDA 11.8, Python 3.8 (e.g. `nvidia/cuda:11.8-cudnn8-runtime-ubuntu22.04` + Python, or a SageMaker PyTorch GPU image).
2. Clone StereoCrafter: `git clone --recursive https://github.com/TencentARC/StereoCrafter`.
3. Install dependencies: `pip install -r requirements.txt`, then `cd dependency/Forward-Warp && ./install.sh`.
4. In the container entrypoint or first request: if `HF_TOKEN_ARN` is set, fetch the secret, then download SVD, DepthCrafter, and StereoCrafter weights from Hugging Face into `./weights`.
5. In `serve.py`, replace `run_inference_stub()` with: download segment from S3 to temp file, run depth_splatting_inference.py, then inpainting_inference.py (with the correct `--pre_trained_path` and `--unet_path`), then upload the final output to `s3_output_uri`.
