"""Download pinned, public language assets for the local assessment demo."""

from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

BASE = Path(os.getenv("HOTEL_MODELS_DIR", ROOT / ".runtime/languages"))
MODELS = {
    "speech": (
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "README.md"],
    ),
    "translation": (
        "mydubber-org/nllb-200-distilled-600M-ct2-int8",
        "9e63a771e9ec358ef812d2ea149d97e16d5f8cee",
        [
            "config.json",
            "model.bin",
            "sentencepiece.bpe.model",
            "shared_vocabulary.json",
            "LICENSE",
            "README.md",
        ],
    ),
}

if __name__ == "__main__":
    from huggingface_hub import snapshot_download

    for kind, (repo, revision, files) in MODELS.items():
        snapshot_download(
            repo,
            revision=revision,
            allow_patterns=files,
            local_dir=BASE / kind,
            max_workers=2,
        )
        print(kind, "ready", flush=True)
