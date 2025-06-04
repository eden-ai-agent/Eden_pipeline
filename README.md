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

### 🛡️ Redaction & Security
- PHI redaction using Presidio or Azure NLP
- Outputs clean `redacted.txt` and `redacted.wav`
- Password-based encryption now uses an increased number of iterations (PBKDF2) to provide stronger protection for the master key.

### 📜 Audit Trail
- JSON log of all user actions (recording, redaction, toggles, etc.)
- Tabulated view in GUI

---

## ⚙️ Configuration

Eden Recorder uses a `config.json` file to manage application settings. This file is automatically created with default values if it's missing or found to be corrupted upon startup. You can customize these settings by editing `config.json`:

-   **`sessions_output_dir`**: Specifies the main directory where all session-specific data (audio, transcripts, metadata) will be stored.
    *   Default: `"sessions_output"`
-   **`app_log_file`**: Defines the path for the detailed application log file. This log captures general application events, errors, and debugging information.
    *   Default: `"logs/app.log"`
-   **`audit_log_dir`**: Sets the directory where general audit logs, such as `application_events.log` (tracking application-level events like startup and shutdown), are stored.
    *   Default: `"logs"`

---

## 📁 Output and Logging

### Output Per Session
Each recording session generates a folder typically within the `sessions_output_dir` (configurable). This folder includes:

- `full.wav` – Original audio
- `transcript.txt` – Unredacted transcript (Note: actual filename is `full_transcript_raw.json`)
- `redacted.wav` – Audio with PHI muted (Note: This specific output is not explicitly generated in current code, redaction is on text level)
- `redacted.txt` – Text with PHI replaced (Note: actual filename is `full_transcript_redacted.json`)
- `metadata.json` – Session metadata including detected PII/PHI, file paths, consent status, etc.
- `session_audit_log.jsonl` – Immutable log of actions performed during that specific session.

### Application Logging
In addition to session-specific outputs:

-   **Application Log (`logs/app.log` by default):** A detailed log file that records general application events, status messages, errors, and debugging information. This log undergoes automatic daily rotation to manage disk space effectively, keeping a history of the last 7 days.
-   **General Audit Log (`logs/application_events.log` by default):** Tracks high-level application lifecycle events such as startup, shutdown, and master key setup.

---

## 🛠️ Tech Stack

- `PyQt5` — User interface
- `faster_whisper` — Local transcription
- `Presidio` — PII/PHI redaction (Note: Not currently implemented; TextRedactor is a placeholder)
- `sounddevice`, `soundfile` — Audio handling
- `cryptography` — Optional encryption for session data and master key.
- `numpy` — Numerical operations, used for voice embeddings.
- `torch`, `resemblyzer` — Voice matching, speaker diarization (though resemblyzer itself might not be directly used if `pyannote.audio` or similar is the diarizer).

---

## 🔧 Install & Run (Dev)

```bash
git clone https://github.com/yourname/eden-recorder.git
cd eden-recorder
# It's recommended to use a virtual environment
# python -m venv venv
# source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
# Note: requirements.txt may need to be generated or updated based on all dependencies.
# For PortAudio issues on Linux (needed by sounddevice):
# sudo apt-get install libportaudio2
python app.py
```

The application will create `config.json` on first startup if it doesn't exist. You can customize paths and settings by editing this file.
The application also requires several Python packages like `numpy`, `PyQt5`, `sounddevice`, `soundfile`, `faster-whisper`, `torch`, etc. Ensure these are installed (preferably via `requirements.txt`).
