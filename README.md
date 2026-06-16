# Astra — Your Personal AI Voice Assistant

Astra is a macOS voice assistant built with a "Hey Jarvis" wake word, speech recognition, and Gemini AI for natural language understanding. It runs entirely on your own Mac — no subscriptions, no cloud lock-in.

## Features

- Wake word detection ("Hey Jarvis") running fully on-device via OpenWakeWord
- Voice authentication — Astra only responds to your enrolled voice
- Live web search with Gemini grounding (movie reviews, news, prices, scores)
- Persistent memory across sessions
- Conversation context for natural follow-up questions
- WhatsApp and iMessage sending by voice
- Full Spotify control (play, pause, skip, search, volume)
- App open/close by voice
- Volume and brightness control
- Pomodoro timer and reminders
- Four voice profiles (Friendly, Professional, Jarvis, Minimal)
- Workspace modes (Study, Work, Design, Relax)
- Menu bar app with quick controls
- Typed input via global keyboard shortcut (Cmd+Shift+A)

## Requirements

- macOS 12 (Monterey) or later
- Python 3.10+ (3.14 recommended via Homebrew)
- A free Gemini API key from [aistudio.google.com](https://aistudio.google.com)
- Microphone access

## Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/mysticnight18/astra-ai-assistant.git
   cd astra-ai-assistant
   ```

2. Install dependencies:
   ```bash
   pip3 install -r requirements.txt --break-system-packages
   ```

3. Set your Gemini API key as an environment variable:
   ```bash
   echo 'export GEMINI_API_KEY="your_key_here"' >> ~/.zshrc
   source ~/.zshrc
   ```

4. Open `astra.py` and update these two lines near the top with your details:
   ```python
   USER_NAME = "Your Name"
   CITY      = "Your City"
   ```

5. If you want WhatsApp/iMessage support, open `messaging.py` and replace the placeholder numbers in `PHONE_BOOK` with real contacts.

6. Run Astra:
   ```bash
   python3 astra.py
   ```

7. (Optional) Enroll your voice for authentication:
   ```
   Say: "Hey Jarvis, enroll my voice"
   ```

## Notes

- `astra_memory.json` and `voice_profile.npy` are created automatically on first run and are excluded from version control (see `.gitignore`) since they contain your personal data.
- Astra is under active development. Windows and Android support, a custom wake word, and a packaged `.app` bundle are planned.

## License

This project is open source. Feel free to use, modify, and build on it.
