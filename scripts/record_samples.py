#!/usr/bin/env python3
"""
Astra — Step 1: Record "Hey Astra" voice samples
Records 30 positive samples (you saying "Hey Astra")
and 20 negative samples (you saying other things)
All saved as 16kHz mono WAV — exactly what the trainer needs
"""

import os, sys, time, wave, struct
import pyaudio
import numpy as np

# ── Config ────────────────────────────────────
SAMPLE_RATE   = 16000
CHANNELS      = 1
FORMAT        = pyaudio.paInt16
CHUNK         = 1024
RECORD_SECS   = 2.0      # each clip is 2 seconds
POSITIVE_COUNT= 30        # "Hey Astra" samples
NEGATIVE_COUNT= 20        # other speech samples

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS_DIR       = os.path.join(BASE_DIR, "samples", "positive")
NEG_DIR       = os.path.join(BASE_DIR, "samples", "negative")

os.makedirs(POS_DIR, exist_ok=True)
os.makedirs(NEG_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────
def _clr():     print("\033[H\033[J", end="")
def _green(t):  print(f"\033[92m{t}\033[0m")
def _yellow(t): print(f"\033[93m{t}\033[0m")
def _red(t):    print(f"\033[91m{t}\033[0m")
def _blue(t):   print(f"\033[94m{t}\033[0m")

def beep(high=False):
    freq = 880 if high else 440
    os.system(f"osascript -e 'beep' &")

def record_clip(pa: pyaudio.PyAudio, duration: float = RECORD_SECS) -> bytes:
    stream = pa.open(
        format=FORMAT, channels=CHANNELS,
        rate=SAMPLE_RATE, input=True,
        frames_per_buffer=CHUNK
    )
    frames = []
    total  = int(SAMPLE_RATE / CHUNK * duration)
    for _ in range(total):
        frames.append(stream.read(CHUNK, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    return b"".join(frames)

def save_wav(path: str, data: bytes):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data)

def check_volume(data: bytes) -> float:
    """Return RMS volume 0-1. Below 0.01 = too quiet."""
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    rms     = np.sqrt(np.mean(samples**2)) / 32768.0
    return rms

def record_with_feedback(pa, label: str, path: str, instruction: str) -> bool:
    """Record one clip with volume feedback. Returns True if good."""
    while True:
        _yellow(f"  🎙️  {instruction}")
        print("     Press ENTER when ready, then speak immediately...")
        input()
        print("     ● Recording...", end="", flush=True)
        data = record_clip(pa)
        vol  = check_volume(data)
        print(f" done. Volume: {'▓' * int(vol * 40):<40} {vol:.3f}")

        if vol < 0.005:
            _red("  ✗  Too quiet! Make sure AirPods mic is selected. Try again.")
            continue
        elif vol < 0.02:
            _yellow("  ⚠  A bit quiet. Try speaking louder or closer.")
            print("     Keep this? (y/n): ", end="")
            if input().strip().lower() != "y":
                continue

        save_wav(path, data)
        _green(f"  ✓  Saved: {os.path.basename(path)}")
        return True

# ── Main ──────────────────────────────────────
def main():
    _clr()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  🎙️  Astra — Voice Sample Recorder")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    _blue("  Before you start:")
    print("  • Connect your AirPods and make sure they're the input mic")
    print("    (System Settings → Sound → Input → select AirPods)")
    print("  • Sit in a relatively quiet spot")
    print("  • Speak naturally — same way you'd use Astra daily")
    print("  • Each recording is 2 seconds — say the phrase and stop")
    print()
    print("  Press ENTER to begin...")
    input()

    pa = pyaudio.PyAudio()

    # ── PART 1: Positive samples ("Hey Astra") ──
    _clr()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    _green(f"  PART 1 of 2 — Say 'Hey Astra' ({POSITIVE_COUNT} times)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print("  Tips for best accuracy:")
    print("  • Vary your tone slightly each time (normal, excited, tired)")
    print("  • Try from slightly different distances (30cm, 50cm, 1m)")
    print("  • Say it exactly as you would in real use")
    print()

    done = 0
    # Check which ones already exist
    existing = [f for f in os.listdir(POS_DIR) if f.endswith(".wav")]
    done     = len(existing)
    if done > 0:
        _yellow(f"  Found {done} existing samples — continuing from #{done+1}")

    while done < POSITIVE_COUNT:
        remaining = POSITIVE_COUNT - done
        print(f"\n  [{done+1}/{POSITIVE_COUNT}] ", end="")

        # Vary the instruction slightly
        if done < 10:
            hint = "normal voice"
        elif done < 20:
            hint = "slightly louder"
        elif done < 25:
            hint = "a bit softer"
        else:
            hint = "natural, relaxed"

        path = os.path.join(POS_DIR, f"hey_astra_{done+1:03d}.wav")
        record_with_feedback(
            pa, "positive", path,
            f"Say 'Hey Astra' clearly ({hint})"
        )
        done += 1

        if done % 10 == 0 and done < POSITIVE_COUNT:
            print(f"\n  🎉 {done} done! Take a 10 second break...")
            time.sleep(10)

    _green(f"\n  ✅ All {POSITIVE_COUNT} 'Hey Astra' samples recorded!\n")

    # ── PART 2: Negative samples (other speech) ──
    _clr()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    _green(f"  PART 2 of 2 — Say OTHER phrases ({NEGATIVE_COUNT} times)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print("  These teach Astra what NOT to wake up for.")
    print("  Say anything that is NOT 'Hey Astra':")
    print()

    negative_prompts = [
        "Say: 'Open YouTube'",
        "Say: 'What time is it'",
        "Say: 'Play some music'",
        "Say: 'I need to study'",
        "Say: 'Hey Jarvis' (similar but wrong)",
        "Say: 'Hello how are you'",
        "Say: 'Start coding mode'",
        "Say: 'Hey Google'",
        "Say: 'Pause the music'",
        "Say: 'What is the weather'",
        "Say: 'Open Spotify'",
        "Say: 'Hey Siri'",
        "Say: 'Next song please'",
        "Say: 'Close Safari'",
        "Say: 'Hey Alexa'",
        "Say: 'Turn on study mode'",
        "Say: 'I want to relax'",
        "Say: 'Set a timer'",
        "Say: 'OK Google'",
        "Say: 'Hey there'",
    ]

    done_neg = 0
    existing_neg = [f for f in os.listdir(NEG_DIR) if f.endswith(".wav")]
    done_neg     = len(existing_neg)

    while done_neg < NEGATIVE_COUNT:
        prompt = negative_prompts[done_neg % len(negative_prompts)]
        path   = os.path.join(NEG_DIR, f"negative_{done_neg+1:03d}.wav")
        print(f"\n  [{done_neg+1}/{NEGATIVE_COUNT}] ", end="")
        record_with_feedback(pa, "negative", path, prompt)
        done_neg += 1

    pa.terminate()

    # ── Summary ──
    _clr()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    _green("  ✅  Recording Complete!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Positive samples : {len(os.listdir(POS_DIR))} files")
    print(f"  Negative samples : {len(os.listdir(NEG_DIR))} files")
    print()
    print("  Next step — run the trainer:")
    print("  python3 scripts/train_wake_word.py")
    print()

if __name__ == "__main__":
    main()
