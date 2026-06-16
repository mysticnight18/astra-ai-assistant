#!/usr/bin/env python3
"""
Astra — Step 2: Train "Hey Astra" wake word (onnxruntime version)
Works with Python 3.14 — no tflite needed.
"""

import os, sys, time, shutil, random
import numpy as np
import scipy.io.wavfile as wav_io

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS_DIR   = os.path.join(BASE_DIR, "samples", "positive")
NEG_DIR   = os.path.join(BASE_DIR, "samples", "negative")
AUG_DIR   = os.path.join(BASE_DIR, "samples", "augmented")
MODEL_OUT = os.path.join(BASE_DIR, "hey_astra_verifier.joblib")

# ── Force ONNX model path (bypasses tflite entirely) ──
# These are the system Python 3.12 ONNX models that work on any Python
# Try multiple base models — alexa has broadest phoneme coverage for custom words
ONNX_SEARCH_PATHS = [
    "/opt/homebrew/lib/python3.12/site-packages/openwakeword/resources/models/alexa_v0.1.onnx",
    "/opt/homebrew/lib/python3.12/site-packages/openwakeword/resources/models/hey_mycroft_v0.1.onnx",
    "/opt/homebrew/lib/python3.12/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx",
    "/usr/local/lib/python3.12/dist-packages/openwakeword/resources/models/alexa_v0.1.onnx",
]

SAMPLE_RATE = 16000

def _green(t):  print(f"\033[92m{t}\033[0m")
def _yellow(t): print(f"\033[93m{t}\033[0m")
def _red(t):    print(f"\033[91m{t}\033[0m")
def _blue(t):   print(f"\033[94m{t}\033[0m")

# ── Find ONNX model ────────────────────────────
def find_onnx_model() -> str:
    # Try hardcoded paths first
    for p in ONNX_SEARCH_PATHS:
        if os.path.exists(p):
            return p
    # Search pip installed locations
    try:
        import glob, importlib.util
        spec = importlib.util.find_spec("openwakeword")
        if spec:
            pkg_dir = os.path.dirname(spec.origin)
            matches = (
            glob.glob(os.path.join(pkg_dir, "**", "*alexa*.onnx"), recursive=True) or
            glob.glob(os.path.join(pkg_dir, "**", "*mycroft*.onnx"), recursive=True) or
            glob.glob(os.path.join(pkg_dir, "**", "*jarvis*.onnx"), recursive=True)
        )
            if matches:
                return matches[0]
    except Exception:
        pass
    return None

# ── Audio utils ───────────────────────────────
def load_wav(path: str) -> np.ndarray:
    sr, data = wav_io.read(path)
    if data.ndim > 1:
        data = data[:, 0]
    if sr != SAMPLE_RATE:
        n    = int(len(data) * SAMPLE_RATE / sr)
        data = np.interp(np.linspace(0, len(data)-1, n),
                         np.arange(len(data)), data).astype(np.int16)
    return data.astype(np.int16)

def save_wav(path: str, data: np.ndarray):
    wav_io.write(path, SAMPLE_RATE, data.astype(np.int16))

def augment(data: np.ndarray, kind: str) -> np.ndarray:
    d = data.astype(np.float32)
    if kind == "noise_low":
        d += np.random.normal(0, 200, len(d))
    elif kind == "noise_high":
        d += np.random.normal(0, 600, len(d))
    elif kind == "vol_up":
        d *= random.uniform(1.2, 1.6)
    elif kind == "vol_down":
        d *= random.uniform(0.5, 0.8)
    elif kind == "pitch":
        f = random.uniform(0.92, 1.08)
        n = int(len(d) * f)
        d = np.interp(np.linspace(0, len(d)-1, n), np.arange(len(d)), d)
        d = d[:len(data)] if len(d) > len(data) else np.pad(d, (0, len(data)-len(d)))
    elif kind == "speed_fast":
        n = int(len(d) / random.uniform(1.05, 1.15))
        d = np.interp(np.linspace(0, len(d)-1, n), np.arange(len(d)), d)
        d = np.pad(d, (0, max(0, len(data)-len(d))))[:len(data)]
    elif kind == "speed_slow":
        n = int(len(d) / random.uniform(0.88, 0.95))
        d = np.interp(np.linspace(0, len(d)-1, n), np.arange(len(d)), d)
        d = d[:len(data)] if len(d) > len(data) else np.pad(d, (0, len(data)-len(d)))
    elif kind == "shift":
        s = random.randint(200, 800)
        d = np.pad(d[s:], (0, s))
    return np.clip(d, -32768, 32767).astype(np.int16)

AUGS = ["noise_low","noise_high","vol_up","vol_down","pitch","speed_fast","speed_slow","shift"]

def augment_dir(src: str, dst: str, mult: int = 8) -> int:
    os.makedirs(dst, exist_ok=True)
    wavs  = [f for f in os.listdir(src) if f.endswith(".wav")]
    count = 0
    for w in wavs:
        data = load_wav(os.path.join(src, w))
        shutil.copy(os.path.join(src, w), os.path.join(dst, w))
        count += 1
        for j, kind in enumerate(random.choices(AUGS, k=mult)):
            name = w.replace(".wav", f"_aug{j}_{kind}.wav")
            save_wav(os.path.join(dst, name), augment(data, kind))
            count += 1
    return count

# ── Main ──────────────────────────────────────
def train():
    print("\033[H\033[J", end="")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  🧠  Astra — Training 'Hey Astra' (ONNX mode)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 1. Check samples
    print("\n  [1/5] Checking samples...")
    pos = [f for f in os.listdir(POS_DIR) if f.endswith(".wav")] if os.path.exists(POS_DIR) else []
    neg = [f for f in os.listdir(NEG_DIR) if f.endswith(".wav")] if os.path.exists(NEG_DIR) else []
    if len(pos) < 10:
        _red(f"  ✗  Only {len(pos)} positive samples. Need at least 10.")
        _red("     Run: python3 scripts/record_samples.py")
        sys.exit(1)
    if len(neg) < 5:
        _red(f"  ✗  Only {len(neg)} negative samples. Need at least 5.")
        sys.exit(1)
    _green(f"     ✅ {len(pos)} positive + {len(neg)} negative samples found")

    # 2. Find ONNX model
    print("\n  [2/5] Finding ONNX model...")
    onnx_path = find_onnx_model()
    if not onnx_path:
        _red("  ✗  ONNX Jarvis model not found.")
        _red("     Run: pip3 install openwakeword --break-system-packages")
        sys.exit(1)
    model_basename = os.path.basename(onnx_path)
    model_key      = model_basename.replace(".onnx", "")
    _green(f"     ✅ Found: {model_basename} (key: {model_key})")

    # 3. Install onnxruntime if needed
    print("\n  [3/5] Checking onnxruntime...")
    try:
        import onnxruntime
        _green(f"     ✅ onnxruntime {onnxruntime.__version__} ready")
    except ImportError:
        _yellow("     Installing onnxruntime...")
        os.system("pip3 install onnxruntime --break-system-packages")
        try:
            import onnxruntime
            _green(f"     ✅ onnxruntime installed")
        except ImportError:
            _red("  ✗  onnxruntime install failed.")
            sys.exit(1)

    # 4. Augment dataset
    print("\n  [4/5] Augmenting dataset (8x)...")
    aug_pos = os.path.join(AUG_DIR, "positive")
    aug_neg = os.path.join(AUG_DIR, "negative")
    if os.path.exists(aug_pos): shutil.rmtree(aug_pos)
    if os.path.exists(aug_neg): shutil.rmtree(aug_neg)
    n_pos = augment_dir(POS_DIR, aug_pos, mult=8)
    n_neg = augment_dir(NEG_DIR, aug_neg, mult=8)
    _green(f"     ✅ {n_pos} positive + {n_neg} negative clips after augmentation")

    # 5. Train verifier
    print("\n  [5/5] Training verifier model...")
    print("        Grab a chai ☕ — takes 5-15 minutes...\n")

    # Force Python 3.12's openwakeword (has ONNX models) instead of 3.14's (tflite only)
    os.environ["OWW_FORCE_ONNX"] = "1"
    import sys
    py312_paths = [
        "/opt/homebrew/lib/python3.12/site-packages",
        "/usr/local/lib/python3.12/dist-packages",
    ]
    for p in py312_paths:
        if os.path.exists(p) and p not in sys.path:
            sys.path.insert(0, p)
            print(f"     Using openwakeword from: {p}")
            break

    from openwakeword.custom_verifier_model import train_custom_verifier
    import openwakeword

    pos_clips = sorted([os.path.join(aug_pos, f) for f in os.listdir(aug_pos) if f.endswith(".wav")])
    neg_clips = sorted([os.path.join(aug_neg, f) for f in os.listdir(aug_neg) if f.endswith(".wav")])

    t0 = time.time()
    # Monkey-patch threshold to 0.0 so ALL positive clips get captured
    import openwakeword.custom_verifier_model as cvm
    _orig = cvm.get_reference_clip_features
    def _patched_get(clip, oww, model_name, threshold=0.5, N=5):
        return _orig(clip, oww, model_name, threshold=0.0, N=5)
    cvm.get_reference_clip_features = _patched_get

    train_custom_verifier(
        positive_reference_clips = pos_clips,
        negative_reference_clips = neg_clips,
        output_path              = MODEL_OUT,
        model_name               = onnx_path,
    )
    elapsed = time.time() - t0

    if not os.path.exists(MODEL_OUT):
        _red("  ✗  Model file not created — something went wrong.")
        sys.exit(1)

    size = os.path.getsize(MODEL_OUT) / 1024
    _green(f"\n     ✅ Training complete in {elapsed:.0f}s!")
    _green(f"     ✅ Saved: hey_astra_verifier.joblib ({size:.1f} KB)")

    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    _green("  🎉  'Hey Astra' model trained successfully!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print("  Next step — test it live:")
    print("  python3 scripts/test_wake_word.py")
    print()

if __name__ == "__main__":
    train()
