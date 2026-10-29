"""Prints a new key pair for browser push. Run once and keep the private key secret:

    python -m scripts.vapid_keys

Set STW_VAPID_PUBLIC_KEY and STW_VAPID_PRIVATE_KEY (and STW_VAPID_SUBJECT, a mailto: address) where the API runs.
Changing the pair later silently drops every device's subscription, so people would have to turn alerts on again.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


if __name__ == "__main__":
    vapid = Vapid()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print("STW_VAPID_PUBLIC_KEY=" + _b64(public))
    print("STW_VAPID_PRIVATE_KEY=" + _b64(vapid.private_key.private_numbers().private_value.to_bytes(32, "big")))
