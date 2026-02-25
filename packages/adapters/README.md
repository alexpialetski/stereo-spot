# stereo-spot-adapters

Platform adapter facade: selects cloud implementations (aws-adapters, future gcp-adapters) by the `PLATFORM` environment variable (default `aws`). Applications depend on this package and call `*_from_env()` here; implementation choice is centralized.
