"""Call-scoped worker authentication, independent of database/model imports."""

import os
import hashlib
import hmac


def worker_token(key):
    # Cloud-hosted LiveKit agents receive generated project credentials. Keep
    # our call-scoped HMAC independent of those platform-managed credentials.
    secret = os.environ.get("WAVO_WORKER_SECRET") or os.environ.get(
        "LIVEKIT_API_SECRET"
    )
    if not secret:
        raise PermissionError("Live audio unavailable.")
    return hmac.new(
        secret.encode(), ("voiceflow-turn:" + key).encode(), hashlib.sha256
    ).hexdigest()
