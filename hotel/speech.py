"""Generate fallback audio when the browser has no voice in the guest's language."""

import base64
import ctypes as ct
import io
import wave
from functools import lru_cache
from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
import espeakng_loader

lock = Lock()
worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wavo-speech")


@lru_cache(maxsize=1)
def engine():
    lib = ct.CDLL(espeakng_loader.get_library_path())
    lib.espeak_Initialize.argtypes = [ct.c_int, ct.c_int, ct.c_char_p, ct.c_int]
    rate = lib.espeak_Initialize(
        2, 0, str(Path(espeakng_loader.get_data_path()).parent).encode(), 0
    )
    if rate <= 0:
        raise RuntimeError("Local speech output unavailable.")
    lib.espeak_Synth.argtypes = [
        ct.c_char_p,
        ct.c_size_t,
        ct.c_uint,
        ct.c_int,
        ct.c_uint,
        ct.c_uint,
        ct.c_void_p,
        ct.c_void_p,
    ]
    return lib, rate


def speak(text, lang):
    return worker.submit(synthesize, text, lang).result(timeout=30)


def synthesize(text, lang):
    with lock:
        lib, rate = engine()
        frames = []

        @ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_int, ct.c_void_p)
        def collect(samples, count, events):
            if samples and count:
                frames.append(ct.string_at(samples, count * 2))
            return 0

        lib.espeak_SetSynthCallback(collect)
        if lib.espeak_SetVoiceByName(("cmn" if lang == "zh" else lang).encode()) != 0:
            return ""
        msg = text.encode()
        if lib.espeak_Synth(msg, len(msg) + 1, 0, 1, 0, 1, None, None) != 0:
            return ""
        lib.espeak_Synchronize()
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            wav.writeframes(b"".join(frames))
        return base64.b64encode(out.getvalue()).decode()
