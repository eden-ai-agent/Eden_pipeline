# Eden Recorder

**Eden Recorder** is a privacy-first, AI-enhanced audio capture application designed to securely record, transcribe, redact, and audit spoken conversations. Built to comply with HIPAA-level standards, it is the front end of the Eden data pipeline and trust architecture.

---

## 📦 Features

### 🔴 Recorder
- Real-time audio capture using PyQt5 GUI
- WAV format output
- Background threads prevent UI freezing

### 🧠 Transcription
- Local Whisper (or faster_whisper) model integration
- Accurate transcription from captured audio

### 🛡️ Redaction
- PHI redaction using Presidio or Azure NLP
- Outputs clean `redacted.txt` and `redacted.wav`

### 📜 Audit Trail
- JSON log of all user actions (recording, redaction, toggles, etc.)
- Tabulated view in GUI

---

## 📁 Output Per Session

Each recording session generates a folder with:

- `full.wav` – Original audio
- `transcript.txt` – Unredacted transcript
- `redacted.wav` – Audio with PHI muted
- `redacted.txt` – Text with PHI replaced
- `metadata.json` – Detected PII/PHI info
- `audit.log` – Immutable action log

---

## 🛠️ Tech Stack

- `PyQt5` — User interface
- `faster_whisper` — Local transcription
- `Presidio` — PII/PHI redaction
- `sounddevice`, `soundfile` — Audio handling
- `cryptography` — Optional encryption
- `numpy`, `resemblyzer` — Voice matching (future use)

---

## 🔧 Install & Run (Dev)

```bash
git clone https://github.com/yourname/eden-recorder.git
cd eden-recorder
pip install -r requirements.txt
python app.py
```
