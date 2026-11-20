"""Format system labels for display without changing stored values."""

import re


def words(label: str | None) -> str:
    text = (label or "").replace("Wi-Fi", "WiFi")
    return re.sub(r"(?<=[^\W\d_])[-_]+(?=[^\W\d_])", " ", text)
