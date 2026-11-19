"""Optional Colab encoder experiment. The deployed TF-IDF models remain explainable."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import classification_report
from torch import nn
from transformers import AutoModel, AutoTokenizer

from hotel import nlp
from research.train import frozen_split

BASE = "distilbert/distilbert-base-uncased"
REVISION = "12040accade4e8a0f71eabdb258fecc2e7e948be"


def run(checkpoint=BASE, epochs=3):
    torch.manual_seed(4453)
    torch.set_num_threads(min(4, torch.get_num_threads()))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    data = pd.read_csv(nlp.ROOT / "data/reviews.csv")
    train, test = frozen_split(
        data.drop_duplicates(subset=["source", "review_id"])
        .loc[~data.text.map(nlp.clean).duplicated()]
        .copy()
    )
    targets = ["urgency", "department"]
    labels = {key: sorted(train[key].unique().tolist()) for key in targets}
    revision = REVISION if checkpoint == BASE else None
    tok = AutoTokenizer.from_pretrained(checkpoint, revision=revision)
    encoder = AutoModel.from_pretrained(
        checkpoint, revision=revision, attn_implementation="eager"
    ).to(device)
    encoder.requires_grad_(False)
    # Cache the frozen lower layers. The last pretrained block and both heads learn.
    last = encoder.transformer.layer[-1]
    last.requires_grad_(True)
    heads = nn.ModuleDict(
        {k: nn.Linear(encoder.config.dim, len(labels[k])) for k in targets}
    ).to(device)

    def encode(frame):
        hidden, masks = [], []
        encoder.eval()
        with torch.no_grad():
            for start in range(0, len(frame), 16):
                inputs = tok(
                    frame.text.iloc[start : start + 16].tolist(),
                    truncation=True,
                    padding="max_length",
                    max_length=80,
                    return_tensors="pt",
                ).to(device)
                states = encoder(**inputs, output_hidden_states=True).hidden_states[-2]
                hidden.append(states.to(device="cpu", dtype=torch.float16))
                masks.append(inputs.attention_mask.cpu())
        return torch.cat(hidden), torch.cat(masks)

    def logits(states, masks):
        output = last(
            states.to(device, dtype=torch.float32),
            attn_mask=masks.to(device),
            head_mask=None,
        )[0]
        return {k: head(output[:, 0]) for k, head in heads.items()}

    x, mask = encode(train)
    y = {
        k: torch.tensor([labels[k].index(v) for v in train[k]], device=device)
        for k in targets
    }
    losses = {
        k: nn.CrossEntropyLoss(weight=torch.bincount(y[k]).float().rsqrt())
        for k in targets
    }
    opt = torch.optim.AdamW(
        [
            {"params": last.parameters(), "lr": 5e-5},
            {"params": heads.parameters(), "lr": 5e-4},
        ]
    )
    for epoch in range(epochs):
        last.train()
        for ids in torch.randperm(len(train)).split(16):
            scores = logits(x[ids], mask[ids])
            loss = sum(losses[k](scores[k], y[k][ids]) for k in targets)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                list(last.parameters()) + list(heads.parameters()), 1.0
            )
            opt.step()
        print(f"Finished epoch {epoch + 1}/{epochs}", flush=True)
    del x, mask
    # The architecture, epoch count and learning rates are fixed before test encoding.
    x, mask = encode(test)
    last.eval()
    predictions = {k: [] for k in targets}
    with torch.no_grad():
        for ids in torch.arange(len(test)).split(16):
            for k, scores in logits(x[ids], mask[ids]).items():
                predictions[k].extend(
                    np.array(labels[k])[scores.argmax(1).cpu().numpy()].tolist()
                )
    report = {
        k: classification_report(
            test[k], predictions[k], labels=labels[k], zero_division=0, output_dict=True
        )
        for k in targets
    }
    revision = Path(checkpoint) / "revision.txt"
    metadata = {
        "base": BASE,
        "revision": revision.read_text().strip()
        if revision.exists()
        else encoder.config._commit_hash,
        "train": len(train),
        "test": len(test),
        "labels": labels,
        "epochs": epochs,
        "max_length": 80,
        "results": report,
    }
    folder = nlp.ROOT / "artifacts/distilbert"
    folder.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"last_block": last.cpu().state_dict(), "heads": heads.cpu().state_dict()},
        folder / "trained_layers.pt",
    )
    (folder / "evaluation.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf8"
    )
    print({k: report[k]["macro avg"]["f1-score"] for k in targets}, flush=True)
    return metadata


if __name__ == "__main__":
    import sys

    run(sys.argv[1] if len(sys.argv) > 1 else BASE)
