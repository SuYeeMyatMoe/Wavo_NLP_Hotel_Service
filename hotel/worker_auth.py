"""Call-scoped worker authentication, independent of database/model imports."""

import os
import hashlib
import hmac


def worker_token(key):
    secret = os.environ.get("LIVEKIT_API_SECRET")
    if not secret:
        raise PermissionError("Live audio unavailable.")
    return hmac.new(
        secret.encode(), ("voiceflow-turn:" + key).encode(), hashlib.sha256
    ).hexdigest()
