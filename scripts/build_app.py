#!/usr/bin/env python3
"""
Astra — Build proper macOS .app bundle
Works with /opt/homebrew/bin/python3 (Python 3.14)
"""

import os, sys, shutil, subprocess, plistlib
from pathlib import Path

# ── Config ────────────────────────────────────
PYTHON_PATH = "/opt/homebrew/bin/python3"
APP_NAME    = "Astra"
DESKTOP     = os.path.expanduser("~/Applications")
APP_OUT     = os.path.join(DESKTOP, "Astra.app")
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _green(t):  print(f"\033[92m{t}\033[0m")
def _yellow(t): print(f"\033[93m{t}\033[0m")
def _red(t):    print(f"\033[91m{t}\033[0m")
def _blue(t):   print(f"\033[94m{t}\033[0m")

# ── Icon SVG ──────────────────────────────────
ICON_SVG = '''<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <radialGradient id="bg" cx="50%" cy="45%" r="55%">
      <stop offset="0%" stop-color="#7C6FFF"/>
      <stop offset="100%" stop-color="#1A1560"/>
    </radialGradient>
    <radialGradient id="glow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#9D94FF" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="#7C6FFF" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1024" height="1024" rx="230" fill="#0F0D2E"/>
  <ellipse cx="512" cy="480" rx="380" ry="380" fill="url(#glow)"/>
  <circle cx="512" cy="460" r="300" fill="url(#bg)"/>
  <circle cx="512" cy="460" r="295" fill="none" stroke="#9D94FF" stroke-width="2" stroke-opacity="0.5"/>
  <rect x="462" y="310" width="100" height="180" rx="50" fill="white" fill-opacity="0.95"/>
  <path d="M390 460 Q390 570 512 570 Q634 570 634 460" fill="none" stroke="white" stroke-width="12" stroke-linecap="round"/>
  <line x1="512" y1="570" x2="512" y2="620" stroke="white" stroke-width="12" stroke-linecap="round"/>
  <line x1="462" y1="620" x2="562" y2="620" stroke="white" stroke-width="12" stroke-linecap="round"/>
  <path d="M360 420 Q340 460 360 500" fill="none" stroke="white" stroke-width="8" stroke-linecap="round" stroke-opacity="0.5"/>
  <path d="M320 395 Q290 460 320 525" fill="none" stroke="white" stroke-width="6" stroke-linecap="round" stroke-opacity="0.3"/>
  <path d="M664 420 Q684 460 664 500" fill="none" stroke="white" stroke-width="8" stroke-linecap="round" stroke-opacity="0.5"/>
  <path d="M704 395 Q734 460 704 525" fill="none" stroke="white" stroke-width="6" stroke-linecap="round" stroke-opacity="0.3"/>
  <text x="512" y="790" text-anchor="middle"
        font-family="-apple-system,Helvetica Neue,sans-serif"
        font-size="96" font-weight="700" fill="white" letter-spacing="16">ASTRA</text>
  <circle cx="512" cy="162" r="10" fill="#9D94FF" fill-opacity="0.8"/>
  <circle cx="790" cy="230" r="7" fill="#9D94FF" fill-opacity="0.5"/>
  <circle cx="234" cy="230" r="7" fill="#9D94FF" fill-opacity="0.5"/>
</svg>'''

def make_icns() -> str | None:
    """Build Astra.icns from SVG using macOS tools."""
    assets    = os.path.join(BASE_DIR, "assets")
    os.makedirs(assets, exist_ok=True)
    svg_path  = os.path.join(assets, "icon.svg")
    png_path  = os.path.join(assets, "icon_1024.png")
    iconset   = os.path.join(assets, "Astra.iconset")
    icns_path = os.path.join(assets, "Astra.icns")

    # Write SVG
    with open(svg_path, "w") as f:
        f.write(ICON_SVG)

    # SVG → PNG via rsvg-convert (brew install librsvg)
    converted = False
    r = subprocess.run(
        ["rsvg-convert", "-w", "1024", "-h", "1024", svg_path, "-o", png_path],
        capture_output=True
    )
    if r.returncode == 0 and os.path.exists(png_path):
        converted = True

    if not converted:
        # Fallback: draw a simple purple circle with sips-compatible PNG via Python
        try:
            script = f"""
import struct, zlib, math

def make_png(size, color_bg, color_circle):
    import struct, zlib
    w = h = size
    raw = []
    cx, cy, r = w//2, h//2, int(w*0.44)
    for y in range(h):
        row = [0]
        for x in range(w):
            dx, dy = x-cx, y-cy
            dist = math.sqrt(dx*dx+dy*dy)
            rr = int(w*0.22)
            corner_r = int(w*0.22)
            # Rounded rect background check
            def in_rrect(px,py,rx,ry,rrad):
                if px < rx or px > w-rx or py < ry or py > h-ry: return False
                corners = [(rx,ry),(w-rx,ry),(rx,h-ry),(w-rx,h-ry)]
                for cx2,cy2 in corners:
                    if abs(px-cx2)<rrad and abs(py-cy2)<rrad:
                        return math.sqrt((px-cx2)**2+(py-cy2)**2) < rrad
                return True
            in_bg = in_rrect(x,y,int(w*0.22),int(w*0.22),int(w*0.22))
            in_circ = dist < r
            if in_circ:
                row += [124,111,255,255]
            elif in_bg:
                row += [15,13,46,255]
            else:
                row += [0,0,0,0]
        raw.append(bytes(row))
    def png_chunk(name, data):
        c = zlib.crc32(name+data) & 0xffffffff
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',c)
    sig = b'\\x89PNG\\r\\n\\x1a\\n'
    ihdr= png_chunk(b'IHDR', struct.pack('>IIBBBBB',w,h,8,6,0,0,0))
    raw2= zlib.compress(b''.join(raw))
    idat= png_chunk(b'IDAT', raw2)
    iend= png_chunk(b'IEND', b'')
    return sig+ihdr+idat+iend

data = make_png(1024, (15,13,46), (124,111,255))
with open('{png_path}', 'wb') as f:
    f.write(data)
print('done')
"""
            r2 = subprocess.run([PYTHON_PATH, "-c", script],
                                capture_output=True, timeout=15)
            if os.path.exists(png_path):
                converted = True
        except Exception as e:
            print(f"    Fallback icon error: {e}")

    if not converted:
        _yellow("    ⚠  Icon skipped. Install librsvg for full icon: brew install librsvg")
        return None

    # Build iconset
    os.makedirs(iconset, exist_ok=True)
    sizes = [16, 32, 128, 256, 512]
    for s in sizes:
        subprocess.run(["sips", "-z", str(s), str(s), png_path,
                        "--out", os.path.join(iconset, f"icon_{s}x{s}.png")],
                       capture_output=True)
        subprocess.run(["sips", "-z", str(s*2), str(s*2), png_path,
                        "--out", os.path.join(iconset, f"icon_{s}x{s}@2x.png")],
                       capture_output=True)

    r = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path],
                       capture_output=True)
    if r.returncode == 0 and os.path.exists(icns_path):
        return icns_path
    return None

def build():
    print("\033[H\033[J", end="")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  📦  Building Astra.app")
    print(f"      Python: {PYTHON_PATH}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── 0. Ensure ~/Applications exists ─────
    os.makedirs(os.path.expanduser("~/Applications"), exist_ok=True)

    # ── 1. Clean ──────────────────────────────
    print("\n  [1/6] Cleaning previous build...")
    if os.path.exists(APP_OUT):
        shutil.rmtree(APP_OUT)
    _green("         ✅ Clean")

    # ── 2. Create structure ───────────────────
    print("\n  [2/6] Creating .app structure...")
    contents  = os.path.join(APP_OUT, "Contents")
    macos_dir = os.path.join(contents, "MacOS")
    resources = os.path.join(contents, "Resources")
    logs_dir  = os.path.join(resources, "logs")
    os.makedirs(macos_dir, exist_ok=True)
    os.makedirs(resources, exist_ok=True)
    os.makedirs(logs_dir,  exist_ok=True)
    _green("         ✅ Structure created")

    # ── 3. Copy Astra files ───────────────────
    print("\n  [3/6] Copying Astra files...")
    src_py = os.path.join(BASE_DIR, "astra.py")
    dst_py = os.path.join(resources, "astra.py")
    shutil.copy2(src_py, dst_py)

    # Copy verifier if exists
    verifier = os.path.join(BASE_DIR, "hey_astra_verifier.joblib")
    if os.path.exists(verifier):
        shutil.copy2(verifier, os.path.join(resources, "hey_astra_verifier.joblib"))
        _green("         ✅ Files + verifier copied")
    else:
        _green("         ✅ Files copied")

    # ── 4. Create launcher ────────────────────
    print("\n  [4/6] Creating launcher script...")

    # Get site-packages path for the homebrew python
    result = subprocess.run(
        [PYTHON_PATH, "-c",
         "import site; print(':'.join(site.getsitepackages()))"],
        capture_output=True, text=True
    )
    site_pkgs = result.stdout.strip()

    launcher_content = f"""#!/bin/bash
# Astra.app launcher
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="{site_pkgs}"

RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
LOG="$RESOURCES/logs/astra.log"
ERR="$RESOURCES/logs/astra_error.log"

# Run Astra — redirect output to logs
exec "{PYTHON_PATH}" "$RESOURCES/astra.py" >> "$LOG" 2>> "$ERR"
"""
    launcher_path = os.path.join(macos_dir, "Astra")
    with open(launcher_path, "w") as f:
        f.write(launcher_content)
    os.chmod(launcher_path, 0o755)
    _green("         ✅ Launcher created")

    # ── 5. Build icon ─────────────────────────
    print("\n  [5/6] Building icon...")
    icns = make_icns()
    if icns:
        shutil.copy2(icns, os.path.join(resources, "Astra.icns"))
        _green("         ✅ Icon built")
    else:
        _yellow("         ⚠  Using default icon")

    # ── 6. Write Info.plist ───────────────────
    print("\n  [6/6] Writing Info.plist...")
    plist = {
        "CFBundleName"              : "Astra",
        "CFBundleDisplayName"       : "Astra",
        "CFBundleIdentifier"        : "com.ishant.astra",
        "CFBundleVersion"           : "3.2.0",
        "CFBundleShortVersionString": "3.2",
        "CFBundleExecutable"        : "Astra",
        "CFBundleIconFile"          : "Astra",
        "CFBundlePackageType"       : "APPL",
        "LSMinimumSystemVersion"    : "12.0",
        "LSUIElement"               : True,
        "NSMicrophoneUsageDescription":
            "Astra needs microphone access to hear your voice commands.",
        "NSHighResolutionCapable"   : True,
    }
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump(plist, f)
    _green("         ✅ Info.plist written")

    # ── Auto-launch on login ──────────────────
    print("\n  Setting up auto-launch on login...")
    plist_dir  = os.path.expanduser("~/Library/LaunchAgents")
    plist_file = os.path.join(plist_dir, "com.ishant.astra.plist")
    os.makedirs(plist_dir, exist_ok=True)

    log_path = os.path.join(resources, "logs", "astra.log")
    err_path = os.path.join(resources, "logs", "astra_error.log")

    launch_plist = {
        "Label"             : "com.ishant.astra",
        "ProgramArguments"  : [launcher_path],
        "RunAtLoad"         : True,
        "KeepAlive"         : False,
        "StandardOutPath"   : log_path,
        "StandardErrorPath" : err_path,
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        },
    }
    with open(plist_file, "wb") as f:
        plistlib.dump(launch_plist, f)

    subprocess.run(["launchctl", "unload", plist_file], capture_output=True)
    subprocess.run(["launchctl", "load",   plist_file], capture_output=True)
    _green("         ✅ Auto-launch on login configured")

    # ── Done ──────────────────────────────────
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    _green("  🎉  Astra.app built successfully!")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n  📍 Location: {APP_OUT}")
    print()
    _blue("  To install:")
    print("  1. Drag Astra.app from Desktop → /Applications")
    print("  2. Right-click Astra.app → Open  (first time only)")
    print("  3. Click Open when macOS warns about unidentified developer")
    print("  4. Allow microphone access when prompted")
    print("  5. Look for ◉ in your menu bar top right")
    print()
    _yellow("  To check logs if something goes wrong:")
    print(f"  cat {log_path}")
    print(f"  cat {err_path}")
    print()

if __name__ == "__main__":
    build()
