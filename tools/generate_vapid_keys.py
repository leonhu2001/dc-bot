from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def main() -> int:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_point = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    print("WEB_PUSH_VAPID_PUBLIC_KEY=" + _b64url(public_point))
    print("WEB_PUSH_VAPID_PRIVATE_KEY=" + _b64url(private_der))
    print("WEB_PUSH_VAPID_SUBJECT=mailto:admin@mowanentertainment.com")
    print("\nStore the private key only in web/.env; never commit generated output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
