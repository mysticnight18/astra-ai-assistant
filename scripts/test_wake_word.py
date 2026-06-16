#!/usr/bin/env python3
"""
Astra — Step 3: Test "Hey Astra" wake word live
Shows real-time confidence scores — say "Hey Astra" and watch it trigger
"""

import os, sys, time, inspect
import numpy as np
import pyaudio
import openwakeword
from openwakeword.model import Model as WakeModel

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFIER_PATH = os.path.join(BASE_DIR, "hey_astra_verifier.joblib")
OWW_PATH      = os.path.dirname(inspect.getfile(openwakeword))
JARVIS_ONNX   = os.path.join(OWW_PATH, "resources", "models", "hey_jarvis_v0.1.onnx")

# ── Adjust this if needed ─────────────────────
# Higher = fewer false triggers, may miss some
# Lower  = catches more, may false trigger
THRESHOLD = 0.5

def bar(score: float, width: int = 40) -> str:
    filled = int(score * width)
    color  = "\033[92m" if score > THRESHOLD else \
             "\033[93m" if score > 0.3 else "\033[91m"
    return color + "▓" * filled + "\033[90m" + "░" * (width - filled) + "\033[0m"

def main():
    print("\033[H\033[J", end="")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  🧪  Astra — Hey Astra Live Test")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if not os.path.exists(VERIFIER_PATH):
        print("  ✗  No verifier found. Run train_wake_word.py first.")
        sys.exit(1)

    print("  Loading model...", flush=True)
    model = WakeModel(
        wakeword_model_paths=[JARVIS_ONNX],
        custom_verifier_models={"hey_jarvis_v0.1": VERIFIER_PATH},
        custom_verifier_threshold=THRESHOLD,
        vad_threshold=0.2,
    )
    print(f"\033[92m  ✅ Ready! Threshold: {THRESHOLD}\033[0m")
    print("  Say 'Hey Astra' — Ctrl+C to stop\n")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    CHUNK = 1280
    RATE  = 16000
    pa    = pyaudio.PyAudio()
    stream= pa.open(format=pyaudio.paInt16, channels=1,
                    rate=RATE, input=True, frames_per_buffer=CHUNK)

    COOLDOWN  = 2.0
    last_trig = 0
    frame_n   = 0

    try:
        while True:
            raw   = stream.read(CHUNK, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            preds = model.predict(audio)
            score = max(preds.values()) if preds else 0

            frame_n += 1
            if frame_n % 5 == 0:
                label = f"  Score: {score:.3f} {bar(score)}"
                print(f"\r{label:<70}", end="", flush=True)

            now = time.time()
            if score > THRESHOLD and (now - last_trig) > COOLDOWN:
                last_trig = now
                print(f"\r  \033[92m🎙️  HEY ASTRA DETECTED! score={score:.3f}\033[0m" + " "*20)
                os.system("say -v Samantha 'Yes Ishant?' &")

    except KeyboardInterrupt:
        print(f"\n\n  Threshold used: {THRESHOLD}")
        print("  Too many false triggers? → increase THRESHOLD (e.g. 0.6)")
        print("  Missing real triggers?   → decrease THRESHOLD (e.g. 0.4)")
        print("\n  Happy with it? Run: python3 scripts/build_app.py\n")
    finally:
        stream.stop_stream(); stream.close(); pa.terminate()

if __name__ == "__main__":
    main()
