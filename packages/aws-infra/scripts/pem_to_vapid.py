#!/usr/bin/env python3
"""
Convert an ECDSA P-256 private key (PEM) to VAPID key format (base64url).
Reads JSON from stdin: {"private_key_pem": "<pem string>"}
Outputs JSON to stdout: {"vapid_public_key": "...", "vapid_private_key": "..."}
Used by Terraform external data source for Web Push VAPID secret.
Requires: pip install cryptography
"""
import base64
import json
import sys


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def main() -> None:
    query = json.load(sys.stdin)
    pem = query.get("private_key_pem")
    if not pem:
        sys.exit(1)
    if isinstance(pem, str):
        pem = pem.encode("utf-8")

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend

    key = serialization.load_pem_private_key(pem, password=None, backend=default_backend())
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        sys.exit(2)

    # Public key: uncompressed point (04 || x || y) per X9.62
    pub_bytes = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    # Private key: raw 32-byte scalar
    raw_private = key.private_numbers().private_value.to_bytes(32, "big")

    out = {
        "vapid_public_key": b64url(pub_bytes),
        "vapid_private_key": b64url(raw_private),
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
