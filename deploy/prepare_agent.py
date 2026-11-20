"""Prepare a minimal LiveKit CLI build context, excluding credentials and models."""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".runtime" / "livekit-agent"
MODULES = (
    "__init__.py",
    "voice_worker.py",
    "voice_turns.py",
    "voice_input.py",
    "voice_health.py",
    "worker_auth.py",
    "privacy_logging.py",
)


def main():
    (TARGET / "hotel").mkdir(parents=True, exist_ok=True)
    for name in MODULES:
        shutil.copyfile(ROOT / "hotel" / name, TARGET / "hotel" / name)
    shutil.copyfile(ROOT / "deploy/requirements-agent.txt", TARGET / "requirements.txt")
    dockerfile = (
        (ROOT / "Dockerfile")
        .read_text()
        .replace("COPY deploy/requirements-agent.txt", "COPY requirements.txt")
    )
    (TARGET / "Dockerfile").write_text(dockerfile)
    (TARGET / ".dockerignore").write_text(
        "*\n!Dockerfile\n!requirements.txt\n!hotel/\n"
        + "".join("!hotel/" + name + "\n" for name in MODULES)
    )
    if (ROOT / "livekit.toml").exists():
        shutil.copyfile(ROOT / "livekit.toml", TARGET / "livekit.toml")
    print(TARGET)


if __name__ == "__main__":
    main()
