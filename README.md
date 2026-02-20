# StereoSpot

High-throughput, cost-optimized video processing: upload → chunking → segment processing (inference) → reassembly → final output. Job–worker pattern with cloud-agnostic interfaces; current implementation uses AWS (ECS, S3, SQS, DynamoDB, SageMaker).

## Documentation

- **Published docs:** [https://alexpialetski.github.io/stereo-spot/](https://alexpialetski.github.io/stereo-spot/)
- **Local preview:** `nx start stereo-spot-docs`

## Run tasks

From the repo root:

```sh
npx nx <target> <project-name>
```

Examples: `nx run web-ui:serve`, `nx run-many -t lint test`. See the [documentation](https://alexpialetski.github.io/stereo-spot/docs/intro) for install, tests, and pipeline overview.
