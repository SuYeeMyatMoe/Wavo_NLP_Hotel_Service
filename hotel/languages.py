"""Local guest speech recognition and translation into the classifier's English space."""

import base64
import hashlib
import io
import wave
import re
from functools import lru_cache
from typing import Literal

from hotel.language_models import BASE
from hotel.nlp import analyze

Language = Literal["en", "zh", "hi", "ms", "my"]
InputLanguage = Literal["auto", "en", "zh", "hi", "ms", "my"]
NAMES = {
    "en": "English",
    "zh": "中文",
    "hi": "हिन्दी",
    "ms": "Bahasa Melayu",
    "my": "မြန်မာ",
}
NLLB = {
    "en": "eng_Latn",
    "zh": "zho_Hans",
    "hi": "hin_Deva",
    "ms": "zsm_Latn",
    "my": "mya_Mymr",
}
MAX_BYTES = 2_000_000


@lru_cache(maxsize=1)
def text_detector():
    from langid.langid import LanguageIdentifier, model

    return LanguageIdentifier.from_modelstring(model, norm_probs=True)


def detect_text_language(text, previous="en"):
    # Distinct scripts remain informative even in a short confirmation.
    for code, pattern in [
        ("my", r"[\u1000-\u109f]"),
        ("hi", r"[\u0900-\u097f]"),
        ("zh", r"[\u3400-\u9fff]"),
    ]:
        if re.search(pattern, text):
            return code
    if len(re.sub(r"\s", "", text)) < 12:
        return previous
    ranked = text_detector().rank(text)
    code, confidence = ranked[0]
    # Malay and Indonesian are frequently confused by both pretrained detectors.
    code = "ms" if code == "id" else code
    if code == "ms":
        confidence = sum(
            score for language, score in ranked if language in {"ms", "id"}
        )
    return code if code in NAMES and confidence >= 0.80 else previous


def transcribe_auto(raw, previous="en"):
    segments, info = recognizer().transcribe(
        io.BytesIO(raw),
        language=None,
        beam_size=3,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    if not text:
        return "", previous
    detected = "ms" if info.language == "id" else info.language
    confidence = info.language_probability
    if detected == "ms" and info.all_language_probs:
        confidence = sum(
            score
            for language, score in info.all_language_probs
            if language in {"ms", "id"}
        )
    if detected in NAMES and confidence >= 0.40:
        return text, detected
    # Brief or ambiguous audio keeps the conversational language.
    return transcribe(raw, previous), previous


@lru_cache(maxsize=1)
def translator():
    import ctranslate2
    import sentencepiece as sp

    folder = BASE / "translation"
    return (
        ctranslate2.Translator(
            str(folder), device="cpu", compute_type="int8", intra_threads=4
        ),
        sp.SentencePieceProcessor(model_file=str(folder / "sentencepiece.bpe.model")),
    )


def to_english(text, language):
    return translate(text, language, "en")


def translate(text, language, target):
    if language == target:
        return text
    tr, sp = translator()
    pieces = sp.encode(text, out_type=str)
    batches = [
        [NLLB[language], *pieces[i : i + 256], "</s>"]
        for i in range(0, len(pieces), 256)
    ]
    result = tr.translate_batch(
        batches,
        target_prefix=[[NLLB[target]] for _ in batches],
        beam_size=3,
        max_decoding_length=350,
    )
    return " ".join(sp.decode(item.hypotheses[0][1:]) for item in result).strip()


@lru_cache(maxsize=1)
def recognizer():
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(BASE / "speech"),
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        local_files_only=True,
    )


def wav_bytes(payload):
    try:
        raw = base64.b64decode(payload, validate=True)
        with wave.open(io.BytesIO(raw)) as wav:
            frames = wav.getnframes()
            if not (
                len(raw) <= MAX_BYTES
                and wav.getnchannels() == 1
                and wav.getsampwidth() == 2
                and wav.getframerate() == 16000
                and 0 < frames <= 60 * 16000
                and len(wav.readframes(frames)) == frames * 2
            ):
                raise ValueError
    except (ValueError, EOFError, wave.Error) as exc:
        raise ValueError("Record a mono voice message of up to 60 seconds.") from exc
    return raw


def transcribe(raw, language):
    segments, _ = recognizer().transcribe(
        io.BytesIO(raw),
        language=language,
        beam_size=3,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()


def guest_analysis(text, language, raw=None):
    transcript = ""
    english = ""
    try:
        if language == "auto":
            if raw is not None:
                transcript, language = transcribe_auto(raw)
            else:
                language = detect_text_language(text)
        elif raw is not None:
            transcript = transcribe(raw, language)
        original = transcript or text
        if original:
            english = to_english(original, language)
    except (ImportError, RuntimeError, OSError, ValueError):
        pass  # Preserve the original for staff when inference is unavailable.
    if english and len(english) <= 8000:
        result = analyze(english)
    else:
        result = {
            "urgency": "Unassessed",
            "department": "Front Desk",
            "predictions": {},
            "version": "staff-review",
            "rule": "Listen to or read the original guest message and review its urgency.",
            "room": "",
        }
    result.update(
        text=transcript or text or "Voice message",
        language="en" if language == "auto" else language,
        english=english,
        transcript=transcript,
    )
    if "provenance" in result:
        result["provenance"]["evidence_source"] = (
            "translated English" if language != "en" else "original"
        )
    if raw is not None:
        result["audio_sha256"] = hashlib.sha256(raw).hexdigest()
    return result
