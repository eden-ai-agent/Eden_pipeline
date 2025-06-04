import sys
import re
import os
import numpy as np
import json
from datetime import datetime, timezone
import logging
from logging.handlers import TimedRotatingFileHandler
import queue

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QDialog, QLineEdit
)
from PyQt5.QtCore import QTimer

from consent_dialog import ConsentDialog
from audio_capture import AudioRecorder # Assuming AudioRecorder might raise specific exceptions documented by its library
from vu_meter_widget import VUMeterWidget
from live_transcriber import LiveTranscriber
from live_transcript_widget import LiveTranscriptWidget
from live_diarizer import LiveDiarizer
from text_redactor import TextRedactor
from speech_emotion_recognizer import SpeechEmotionRecognizer
# encryption_utils can raise ValueError, FileNotFoundError, InvalidTag from cryptography.exceptions
from encryption_utils import generate_aes_key, wrap_session_key, encrypt_file, derive_key_from_password, SALT
from ai_training_consent_dialog import AITrainingConsentDialog
from session_summary_dialog import SessionSummaryDialog
from metadata_viewer_dialog import MetadataViewerDialog
from audit_logger import AuditLogger
from config_utils import load_or_create_config, CONFIG_FILE_PATH, DEFAULT_CONFIG # Added

# Initialize configuration
config = load_or_create_config(CONFIG_FILE_PATH, DEFAULT_CONFIG)

# --- Setup Logger (using configuration) ---
# Fallback to DEFAULT_CONFIG values if key is missing, though load_or_create_config should ensure defaults.
app_log_file_path = config.get("app_log_file", DEFAULT_CONFIG["app_log_file"])
log_file_dir = os.path.dirname(app_log_file_path)
if log_file_dir:
    os.makedirs(log_file_dir, exist_ok=True)
else:
    os.makedirs(DEFAULT_CONFIG["audit_log_dir"], exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

fh = TimedRotatingFileHandler(app_log_file_path, when="midnight", backupCount=7)
fh.setLevel(logging.INFO)
sh = logging.StreamHandler()
sh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
sh.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(sh)

# --- Password Dialog ---
# (PasswordDialog class remains unchanged as its error handling is mainly QMessageBox for user feedback)
class PasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Master Password Required")
        self.setModal(True); layout = QVBoxLayout(self)
        self.info_label = QLabel("Enter Master Password for Encryption:")
        layout.addWidget(self.info_label)
        self.password_input = QLineEdit(); self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK"); self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout); self.setLayout(layout); self.setMinimumWidth(300)

    def get_password(self):
        if self.exec_() == QDialog.Accepted:
            password = self.password_input.text()
            if not password:
                logger.warning("Password provided was empty. Encryption will be disabled.")
                QMessageBox.warning(self, "Empty Password", "Password cannot be empty. Encryption will be disabled.")
                return None
            return password
        logger.info("Password dialog cancelled by user.")
        return None

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        logger.info("MainApp initialization started.")
        self.base_output_dir = config.get("sessions_output_dir", DEFAULT_CONFIG["sessions_output_dir"])
        logger.info(f"Session output directory set to: {self.base_output_dir}")

        self.session_consent_status = None; self.session_consent_timestamp = None
        self.session_stop_timestamp = None; self.session_consent_expiry = None
        self.audio_recorder = None; self.live_transcriber = None; self.live_diarizer = None
        self.text_redactor = TextRedactor(); self.speech_emotion_recognizer = None
        self.current_speaker_label = "SPEAKER_UKN"; self.diarization_result_queue = None
        self.emotion_results_queue = None
        self.session_voice_prints = {}; self.session_voice_print_filepaths = {}
        self.session_phi_pii_details = []; self.session_phi_pii_audio_mute_segments = []
        self.session_emotion_annotations = []; self.full_raw_transcript_segments = []
        self.full_redacted_transcript_segments = []; self.ai_training_consents = {}
        self.redacted_text_queue = queue.Queue()
        self.current_session_id = None
        self.current_session_dir = None; self.current_session_standard_dir = None
        self.current_session_encrypted_dir = None; self.current_session_key = None
        self.master_key = None
        self.general_audit_logger = None
        self.audit_logger = None

        self._setup_audit_loggers()
        self._setup_master_key()
        self._init_ui()

        if self.general_audit_logger: self.general_audit_logger.log_action("APP_STARTUP_COMPLETE", {"encryption_enabled": self.master_key is not None})
        else: logger.warning("General audit logger not available after setup.")

        self.diarization_update_timer = QTimer(self); self.diarization_update_timer.timeout.connect(self._update_current_speaker); self.diarization_update_timer.setInterval(200)
        self.text_processing_timer = QTimer(self); self.text_processing_timer.timeout.connect(self._process_transcribed_data); self.text_processing_timer.setInterval(100)
        self.emotion_update_timer = QTimer(self); self.emotion_update_timer.timeout.connect(self._update_emotion_display); self.emotion_update_timer.setInterval(300)
        logger.info("MainApp initialization complete.")

    def _setup_audit_loggers(self):
        audit_dir = config.get("audit_log_dir", DEFAULT_CONFIG["audit_log_dir"])
        try:
            os.makedirs(audit_dir, exist_ok=True)
        except OSError as e: # Specific error for os.makedirs
            logger.critical(f"Failed to create audit log directory '{audit_dir}': {e}", exc_info=True)
            # Depending on policy, might want to exit or disable audit logging.
            # For now, it will try to init AuditLogger which might fail again.

        general_audit_log_path = os.path.join(audit_dir, "application_events.log")
        self.general_audit_logger = AuditLogger(general_audit_log_path) # AuditLogger has its own init error logging
        logger.info(f"General audit logger configured at: {general_audit_log_path}")

    # _setup_master_key, _init_ui, open_metadata_viewer, run_consent_procedure remain largely unchanged
    # as their primary error modes are user interactions (dialogs) or config (already handled).
    # os.makedirs in open_metadata_viewer can also raise OSError.
    def _setup_master_key(self):
        logger.info("Setting up master key.")
        dialog = PasswordDialog(self)
        user_password = dialog.get_password()
        if user_password:
            try:
                self.master_key = derive_key_from_password(user_password, salt=SALT)
                logger.info("Master key derived successfully.")
                if self.general_audit_logger: self.general_audit_logger.log_action("MASTER_KEY_DERIVED", {"derivation_method": "PBKDF2-SHA256"})
            except ValueError as e: # derive_key_from_password can raise ValueError
                 logger.error(f"Error deriving master key (likely empty password after dialog): {e}", exc_info=True)
                 self.master_key = None
                 QMessageBox.warning(self, "Master Key Error", f"Could not derive master key: {e}")
            except Exception as e: # Catch other unexpected errors from KDF
                 logger.critical(f"Unexpected error deriving master key: {e}", exc_info=True)
                 self.master_key = None
                 QMessageBox.error(self, "Critical Key Error", f"An unexpected error occurred during master key derivation: {e}")

        else: # No password from dialog
            self.master_key = None
            logger.warning("Master key not provided or password was empty. Encryption disabled.")
            if self.general_audit_logger: self.general_audit_logger.log_action("MASTER_KEY_NOT_PROVIDED", {"encryption_status": "disabled"})
            QMessageBox.warning(self, "Encryption Disabled", "No master password provided or it was empty. File encryption will be disabled.")

    def _init_ui(self):
        logger.info("Initializing UI.")
        self.setWindowTitle("Eden Recorder"); self.setGeometry(100, 100, 500, 550)
        layout = QVBoxLayout(self)
        initial_status = "Eden Recorder: Ready to record. Click 'Record' to start."
        if self.master_key is None: initial_status += " (Encryption DISABLED)"
        else: initial_status += " (Encryption ENABLED)"
        self.status_label = QLabel(initial_status); layout.addWidget(self.status_label)
        self.vu_meter = VUMeterWidget(); layout.addWidget(self.vu_meter)
        self.transcript_widget = LiveTranscriptWidget(transcript_text_queue=self.redacted_text_queue); layout.addWidget(self.transcript_widget)
        self.emotion_label = QLabel("Emotion: ---"); layout.addWidget(self.emotion_label)

        main_button_layout = QHBoxLayout()
        self.record_button = QPushButton("Record"); self.record_button.clicked.connect(self._on_record_button_clicked); main_button_layout.addWidget(self.record_button)
        self.stop_button = QPushButton("Stop"); self.stop_button.clicked.connect(self._on_stop_button_clicked); self.stop_button.setEnabled(False); main_button_layout.addWidget(self.stop_button)
        layout.addLayout(main_button_layout)

        utility_button_layout = QHBoxLayout()
        self.view_metadata_button = QPushButton("View Session Metadata")
        self.view_metadata_button.clicked.connect(self.open_metadata_viewer)
        utility_button_layout.addWidget(self.view_metadata_button)
        utility_button_layout.addStretch(1)
        layout.addLayout(utility_button_layout)

        self.setLayout(layout)
        logger.info("UI Initialized.")

    def open_metadata_viewer(self):
        logger.info("Opening metadata viewer dialog.")
        if not os.path.exists(self.base_output_dir):
            try:
                os.makedirs(self.base_output_dir, exist_ok=True)
                logger.info(f"Created base output directory for metadata viewer: {self.base_output_dir}")
            except OSError as e:
                logger.error(f"Failed to create base output directory '{self.base_output_dir}': {e}", exc_info=True)
                QMessageBox.warning(self, "Directory Error", f"Could not create directory for sessions: {e}")
                return # Don't open dialog if dir creation failed

        dialog = MetadataViewerDialog(parent=self, initial_dir=self.base_output_dir)
        dialog.exec_()
        logger.info("Metadata viewer dialog closed.")

    def run_consent_procedure(self):
        logger.info("Running consent procedure.")
        dialog = ConsentDialog(self)
        dialog.exec_()
        self.session_consent_status = dialog.get_consent_status()
        self.session_consent_timestamp = dialog.get_consent_timestamp()
        if self.session_consent_status and self.session_consent_timestamp:
            try:
                self.session_consent_expiry = self.session_consent_timestamp.replace(year=self.session_consent_timestamp.year + 1)
                logger.info(f"Consent given, expiry set to: {self.session_consent_expiry.isoformat()}")
            except ValueError:
                self.session_consent_expiry = self.session_consent_timestamp.replace(year=self.session_consent_timestamp.year + 1, day=28)
                logger.info(f"Consent given (leap year adjustment), expiry set to: {self.session_consent_expiry.isoformat()}")
        else:
            self.session_consent_expiry = None
            logger.warning("Consent not given or timestamp not available.")
        return self.session_consent_status


    def _on_record_button_clicked(self):
        logger.info("Record button clicked.")
        if not self.run_consent_procedure():
            logger.warning("Recording aborted due to lack of consent.")
            QMessageBox.warning(self, "Consent Required", "Recording cannot start without user consent.")
            return

        self.current_session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3] + "Z"
        logger.info(f"New session ID: {self.current_session_id}")

        self.current_session_dir = os.path.join(self.base_output_dir, self.current_session_id)
        self.current_session_standard_dir = os.path.join(self.current_session_dir, "standard_data")
        self.current_session_encrypted_dir = os.path.join(self.current_session_dir, "encrypted_data")

        try:
            os.makedirs(self.current_session_standard_dir, exist_ok=True)
            os.makedirs(self.current_session_encrypted_dir, exist_ok=True)
            logger.info(f"Session directories created: Standard='{self.current_session_standard_dir}', Encrypted='{self.current_session_encrypted_dir}'")
        except OSError as e:
            logger.critical(f"Failed to create session directories for '{self.current_session_id}': {e}", exc_info=True)
            QMessageBox.critical(self, "Directory Creation Error", f"Could not create session directories: {e}")
            self._reset_session_specific_vars() # Clean up
            return

        session_audit_log_path = os.path.join(self.current_session_standard_dir, "session_audit_log.jsonl")
        self.audit_logger = AuditLogger(session_audit_log_path)
        logger.info(f"Session audit logger configured for: {session_audit_log_path}")
        if self.audit_logger: self.audit_logger.log_action("SESSION_START", {"session_id": self.current_session_id})

        if self.master_key:
            try:
                self.current_session_key = generate_aes_key()
                logger.info(f"Session AES key generated for session {self.current_session_id}.")
                if self.audit_logger: self.audit_logger.log_action("SESSION_KEY_GENERATED", {"session_id": self.current_session_id})
            except Exception as e: # generate_aes_key might raise from os.urandom
                 logger.critical(f"Failed to generate session key: {e}", exc_info=True)
                 QMessageBox.critical(self, "Key Generation Error", f"Could not generate session key: {e}")
                 self._reset_session_specific_vars()
                 return
        else: # No master key
            self.current_session_key = None
            logger.warning(f"Master key not available. Session {self.current_session_id} will not be encrypted.")
            if self.audit_logger: self.audit_logger.log_action("SESSION_KEY_NOT_GENERATED", {"reason": "Master key missing", "session_id": self.current_session_id})

        raw_audio_filename = "raw_session_audio.wav"
        raw_audio_path_standard = os.path.join(self.current_session_standard_dir, raw_audio_filename)

        try:
            self.audio_recorder = AudioRecorder(output_filepath=raw_audio_path_standard, vu_meter_callback=self.vu_meter.update_vu)
            self.audio_recorder.start_recording()
            logger.info(f"Audio recording started. Output to: {raw_audio_path_standard}")
            if self.audit_logger: self.audit_logger.log_action("AUDIO_RECORDING_STARTED", {"path": raw_audio_path_standard})
        except (IOError, OSError) as e: # More specific for file/device access
            logger.error(f"Error initializing audio recorder (I/O or OS error): {e}", exc_info=True)
            QMessageBox.critical(self, "Audio Error", f"Could not start audio recording (I/O): {e}")
            if self.audit_logger: self.audit_logger.log_action("AUDIO_RECORDING_FAILED", {"error": str(e)})
            self._reset_session_specific_vars()
            return
        except Exception as e: # Catch other errors from AudioRecorder (e.g. sounddevice.PortAudioError if used)
            logger.error(f"Error initializing audio recorder: {e}", exc_info=True)
            QMessageBox.critical(self, "Audio Error", f"Could not start audio recording: {e}")
            if self.audit_logger: self.audit_logger.log_action("AUDIO_RECORDING_FAILED", {"error": str(e)})
            self._reset_session_specific_vars()
            return
        # ... (rest of _on_record_button_clicked method as before)
        self.diarization_result_queue = queue.Queue()
        self.live_diarizer = LiveDiarizer(
            audio_stream_callback=self.audio_recorder.get_latest_chunk_for_diarization,
            result_queue=self.diarization_result_queue,
            session_id=self.current_session_id
        )
        self.live_diarizer.start_diarization()
        self.diarization_update_timer.start()
        logger.info("Live diarization started.")

        self.live_transcriber = LiveTranscriber(audio_stream_callback=self.audio_recorder.get_latest_chunk_for_transcription)
        self.live_transcriber.start_transcription()
        self.text_processing_timer.start()
        logger.info("Live transcription started.")

        self.emotion_results_queue = queue.Queue()
        self.speech_emotion_recognizer = SpeechEmotionRecognizer(
            audio_chunk_provider_callback=self.audio_recorder.get_latest_chunk_for_emotion,
            result_queue=self.emotion_results_queue,
            session_id=self.current_session_id
        )
        self.speech_emotion_recognizer.start_recognition()
        self.emotion_update_timer.start()
        logger.info("Speech emotion recognition started.")

        self.transcript_widget.start_updates()
        self.status_label.setText(f"Recording session: {self.current_session_id}...")
        self.record_button.setEnabled(False); self.stop_button.setEnabled(True)
        logger.info("UI updated for active recording session.")


    def _map_pii_chars_to_audio_time(self, pii_entity, word_timestamps, segment_text): return None, None
    def _process_transcribed_data(self): pass
    def _update_current_speaker(self): pass
    def _update_emotion_display(self): pass

    def _save_and_encrypt_voice_embeddings(self):
        logger.info("Attempting to save and encrypt voice embeddings.")
        any_saved = False; any_encrypted = False
        if not self.session_voice_prints:
            logger.info("No voice prints captured in this session to save.")
            return False, False

        for speaker_id, embedding_data in self.session_voice_prints.items():
            filename = f"voice_embedding_{speaker_id}.npy"
            filepath_standard = os.path.join(self.current_session_standard_dir, filename)
            try:
                np.save(filepath_standard, embedding_data['embedding']) # Can raise IOError/OSError
                self.session_voice_print_filepaths[speaker_id] = {"standard": filepath_standard, "encrypted": None}
                logger.info(f"Voice embedding for {speaker_id} saved to {filepath_standard}")
                any_saved = True
                if self.audit_logger: self.audit_logger.log_action("FILE_SAVED_STANDARD", {"type": "voice_embedding", "speaker": speaker_id, "path": filepath_standard})

                if self.master_key and self.current_session_key:
                    filepath_encrypted = os.path.join(self.current_session_encrypted_dir, f"{filename}.enc")
                    encrypt_file(filepath_standard, self.current_session_key, filepath_encrypted) # Can raise FileNotFoundError, ValueError, InvalidTag
                    self.session_voice_print_filepaths[speaker_id]["encrypted"] = filepath_encrypted
                    logger.info(f"Encrypted voice embedding for {speaker_id} to {filepath_encrypted}")
                    any_encrypted = True
                    if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTED", {"type": "voice_embedding", "speaker": speaker_id, "path": filepath_encrypted})
                elif self.master_key is None:
                     logger.warning(f"Master key not set. Skipping encryption for voice embedding of {speaker_id}.")
            except (IOError, OSError) as e:
                logger.error(f"I/O error processing voice embedding for {speaker_id}: {e}", exc_info=True)
                if self.audit_logger: self.audit_logger.log_action("VOICE_EMBEDDING_IO_ERROR", {"speaker": speaker_id, "error": str(e)})
            except ValueError as e: # From encryption_utils or np.save if data is bad
                logger.error(f"Value error processing voice embedding for {speaker_id}: {e}", exc_info=True)
                if self.audit_logger: self.audit_logger.log_action("VOICE_EMBEDDING_VALUE_ERROR", {"speaker": speaker_id, "error": str(e)})
            except Exception as e: # Fallback for other errors (e.g. cryptography.exceptions.InvalidTag though unlikely here)
                logger.error(f"Unexpected error processing voice embedding for {speaker_id}: {e}", exc_info=True)
                if self.audit_logger: self.audit_logger.log_action("VOICE_EMBEDDING_ERROR", {"speaker": speaker_id, "error": str(e)})
        return any_saved, any_encrypted

    def _generate_metadata_dict(self) -> dict: # (No significant I/O here, mostly data compilation)
        logger.debug("Generating metadata dictionary.")
        # ... (content as before)
        return {
            "session_id": self.current_session_id,
            "start_time_utc": self.audio_recorder.start_time.isoformat() if self.audio_recorder and self.audio_recorder.start_time else None,
            "stop_time_utc": self.session_stop_timestamp.isoformat() if self.session_stop_timestamp else None,
            "duration_seconds": (self.session_stop_timestamp - self.audio_recorder.start_time).total_seconds() if self.audio_recorder and self.audio_recorder.start_time and self.session_stop_timestamp else None,
            "encryption_status": "enabled" if self.master_key and self.current_session_key else "disabled",
            "consent_status": self.session_consent_status,
            "consent_timestamp_utc": self.session_consent_timestamp.isoformat() if self.session_consent_timestamp else None,
            "consent_expiry_utc": self.session_consent_expiry.isoformat() if self.session_consent_expiry else None,
            "files": {
                "raw_audio_standard": os.path.join(self.current_session_standard_dir, "raw_session_audio.wav") if self.current_session_standard_dir else None,
                "raw_audio_encrypted": os.path.join(self.current_session_encrypted_dir, "raw_session_audio.wav.enc") if self.master_key and self.current_session_encrypted_dir else None,
                "full_transcript_raw_standard": os.path.join(self.current_session_standard_dir, "full_transcript_raw.json") if self.current_session_standard_dir else None,
                "full_transcript_raw_encrypted": os.path.join(self.current_session_encrypted_dir, "full_transcript_raw.json.enc") if self.master_key and self.current_session_encrypted_dir else None,
                "full_transcript_redacted_standard": os.path.join(self.current_session_standard_dir, "full_transcript_redacted.json") if self.current_session_standard_dir else None,
                "full_transcript_redacted_encrypted": os.path.join(self.current_session_encrypted_dir, "full_transcript_redacted.json.enc") if self.master_key and self.current_session_encrypted_dir else None,
                "session_audit_log_standard": os.path.join(self.current_session_standard_dir, "session_audit_log.jsonl") if self.current_session_standard_dir else None,
                "session_audit_log_encrypted": os.path.join(self.current_session_encrypted_dir, "session_audit_log.jsonl.enc") if self.master_key and self.current_session_encrypted_dir else None,
                "voice_embeddings_standard": {sid: paths["standard"] for sid, paths in self.session_voice_print_filepaths.items()},
                "voice_embeddings_encrypted": {sid: paths["encrypted"] for sid, paths in self.session_voice_print_filepaths.items() if paths.get("encrypted")},
                "wrapped_session_key": os.path.join(self.current_session_dir, "session_key.ek") if self.master_key and self.current_session_dir else None,
            },
            "phi_pii_details": self.session_phi_pii_details,
            "phi_pii_audio_mute_segments": self.session_phi_pii_audio_mute_segments,
            "emotion_annotations": self.session_emotion_annotations,
            "ai_training_consents": self.ai_training_consents,
            "system_details": {
                "platform": sys.platform,
                "python_version": sys.version
            },
            "configuration_used": config
        }


    def _on_stop_button_clicked(self):
        logger.info("Stop button clicked. Finalizing session.")
        self.session_stop_timestamp = datetime.now(timezone.utc)

        if self.audio_recorder and self.audio_recorder.is_recording:
            logger.info("Stopping audio recorder.")
            raw_audio_path = self.audio_recorder.output_filepath
            self.audio_recorder.stop_recording() # Assuming this can't fail or has own error handling
            logger.info(f"Audio recording stopped. Raw audio at: {raw_audio_path}")
            if self.audit_logger: self.audit_logger.log_action("AUDIO_RECORDING_STOPPED", {"path": raw_audio_path})

            if self.master_key and self.current_session_key and os.path.exists(raw_audio_path):
                encrypted_audio_path = os.path.join(self.current_session_encrypted_dir, "raw_session_audio.wav.enc")
                try:
                    encrypt_file(raw_audio_path, self.current_session_key, encrypted_audio_path)
                    logger.info(f"Raw audio encrypted to: {encrypted_audio_path}")
                    if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTED", {"type": "raw_audio", "path": encrypted_audio_path})
                except (IOError, OSError, FileNotFoundError) as e: # encrypt_file can raise FileNotFoundError
                    logger.error(f"I/O error encrypting raw audio file '{raw_audio_path}': {e}", exc_info=True)
                    if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTION_IO_FAILED", {"type": "raw_audio", "error": str(e)})
                except ValueError as e: # From encryption
                    logger.error(f"Value error encrypting raw audio file '{raw_audio_path}': {e}", exc_info=True)
                    if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTION_VALUE_ERROR", {"type": "raw_audio", "error": str(e)})
                except Exception as e: # Fallback
                    logger.error(f"Unexpected error encrypting raw audio file '{raw_audio_path}': {e}", exc_info=True)
                    if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTION_FAILED", {"type": "raw_audio", "error": str(e)})
            elif self.master_key is None:
                 logger.warning("Master key not set. Skipping encryption of raw audio.")
        else:
            logger.warning("Audio recorder not active or already stopped.")

        # ... (Stopping timers and workers) ...
        logger.info("Stopping timers and worker threads...")
        if self.diarization_update_timer.isActive(): self.diarization_update_timer.stop()
        if self.text_processing_timer.isActive(): self.text_processing_timer.stop()
        if self.emotion_update_timer.isActive(): self.emotion_update_timer.stop()
        if self.live_diarizer: self.live_diarizer.stop_diarization(); logger.debug("Live diarizer stopped.")
        if self.live_transcriber: self.live_transcriber.stop_transcription(); logger.debug("Live transcriber stopped.")
        if self.speech_emotion_recognizer: self.speech_emotion_recognizer.stop_recognition(); logger.debug("Speech emotion recognizer stopped.")
        if self.transcript_widget: self.transcript_widget.stop_updates(); logger.debug("Transcript widget updates stopped.")
        if self.vu_meter: self.vu_meter.timer.stop(); logger.debug("VU meter timer stopped.")

        self._save_and_encrypt_voice_embeddings() # Already updated with specific exceptions

        # Save transcripts (raw and redacted)
        raw_transcript_path_standard = os.path.join(self.current_session_standard_dir, "full_transcript_raw.json")
        try:
            with open(raw_transcript_path_standard, 'w', encoding='utf-8') as f: json.dump(self.full_raw_transcript_segments, f, indent=4)
            logger.info(f"Raw transcript saved to {raw_transcript_path_standard}")
            if self.audit_logger: self.audit_logger.log_action("FILE_SAVED_STANDARD", {"type": "raw_transcript", "path": raw_transcript_path_standard})
            if self.master_key and self.current_session_key:
                raw_transcript_path_encrypted = os.path.join(self.current_session_encrypted_dir, "full_transcript_raw.json.enc")
                encrypt_file(raw_transcript_path_standard, self.current_session_key, raw_transcript_path_encrypted)
                logger.info(f"Raw transcript encrypted to {raw_transcript_path_encrypted}")
                if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTED", {"type": "raw_transcript", "path": raw_transcript_path_encrypted})
            elif self.master_key is None: logger.warning("Master key not set. Skipping encryption of raw transcript.")
        except (IOError, OSError) as e: logger.error(f"I/O error saving/encrypting raw transcript: {e}", exc_info=True)
        except TypeError as e: logger.error(f"Type error saving raw transcript (data not JSON serializable?): {e}", exc_info=True)
        except ValueError as e: logger.error(f"Value error during raw transcript encryption: {e}", exc_info=True) # From encrypt_file
        except Exception as e: logger.error(f"Unexpected error saving/encrypting raw transcript: {e}", exc_info=True)

        redacted_transcript_path_standard = os.path.join(self.current_session_standard_dir, "full_transcript_redacted.json")
        try:
            with open(redacted_transcript_path_standard, 'w', encoding='utf-8') as f: json.dump(self.full_redacted_transcript_segments, f, indent=4)
            logger.info(f"Redacted transcript saved to {redacted_transcript_path_standard}")
            if self.audit_logger: self.audit_logger.log_action("FILE_SAVED_STANDARD", {"type": "redacted_transcript", "path": redacted_transcript_path_standard})
            if self.master_key and self.current_session_key:
                redacted_transcript_path_encrypted = os.path.join(self.current_session_encrypted_dir, "full_transcript_redacted.json.enc")
                encrypt_file(redacted_transcript_path_standard, self.current_session_key, redacted_transcript_path_encrypted)
                logger.info(f"Redacted transcript encrypted to {redacted_transcript_path_encrypted}")
                if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTED", {"type": "redacted_transcript", "path": redacted_transcript_path_encrypted})
            elif self.master_key is None: logger.warning("Master key not set. Skipping encryption of redacted transcript.")
        except (IOError, OSError) as e: logger.error(f"I/O error saving/encrypting redacted transcript: {e}", exc_info=True)
        except TypeError as e: logger.error(f"Type error saving redacted transcript: {e}", exc_info=True)
        except ValueError as e: logger.error(f"Value error during redacted transcript encryption: {e}", exc_info=True)
        except Exception as e: logger.error(f"Unexpected error saving/encrypting redacted transcript: {e}", exc_info=True)

        ai_consent_dialog = AITrainingConsentDialog(self.current_session_id, parent=self)
        ai_consent_dialog.exec_()
        self.ai_training_consents = ai_consent_dialog.get_consents()
        logger.info(f"AI training consents obtained: {self.ai_training_consents}")
        if self.audit_logger: self.audit_logger.log_action("AI_TRAINING_CONSENT_OBTAINED", {"session_id": self.current_session_id, "consents": self.ai_training_consents})

        metadata_content = self._generate_metadata_dict()
        logger.info("Metadata dictionary generated for session stop (includes configuration).")
        metadata_saved, metadata_encrypted = False, False
        if self.current_session_standard_dir and metadata_content:
            standard_metadata_path = os.path.join(self.current_session_standard_dir, "metadata.json")
            try:
                with open(standard_metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata_content, f, indent=4)
                logger.info(f"Metadata saved to {standard_metadata_path}"); metadata_saved = True
                if self.audit_logger: self.audit_logger.log_action("FILE_SAVED_STANDARD", {"type": "metadata_json", "path": standard_metadata_path})

                if self.master_key and self.current_session_key:
                    encrypted_metadata_path = os.path.join(self.current_session_encrypted_dir, "metadata.json.enc")
                    encrypt_file(standard_metadata_path, self.current_session_key, encrypted_metadata_path)
                    logger.info(f"Encrypted metadata saved to {encrypted_metadata_path}"); metadata_encrypted = True
                    if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTED", {"type": "metadata_json", "path": encrypted_metadata_path})
                elif self.master_key is None and metadata_saved: logger.warning("Master key not set. Skipping encryption of metadata.json.")
            except (IOError, OSError) as e: logger.error(f"I/O error saving or encrypting metadata.json: {e}", exc_info=True)
            except TypeError as e: logger.error(f"Type error saving metadata.json: {e}", exc_info=True)
            except ValueError as e: logger.error(f"Value error encrypting metadata.json: {e}", exc_info=True) # From encrypt_file
            except Exception as e: logger.critical(f"Unexpected critical error saving or encrypting metadata.json: {e}", exc_info=True) # Fallback
        elif not metadata_content: logger.warning("Metadata content is empty. Skipping save for metadata.json.")
        elif not self.current_session_standard_dir: logger.error("Session standard directory not set. Cannot save metadata.json.")

        # Encrypt session audit log
        if self.audit_logger and self.audit_logger.log_filepath and os.path.exists(self.audit_logger.log_filepath):
            if self.master_key and self.current_session_key:
                encrypted_audit_log_path = os.path.join(self.current_session_encrypted_dir, "session_audit_log.jsonl.enc")
                try:
                    encrypt_file(self.audit_logger.log_filepath, self.current_session_key, encrypted_audit_log_path)
                    logger.info(f"Session audit log encrypted to: {encrypted_audit_log_path}")
                except (IOError, OSError, FileNotFoundError) as e: logger.error(f"I/O error encrypting session audit log: {e}", exc_info=True)
                except ValueError as e: logger.error(f"Value error encrypting session audit log: {e}", exc_info=True)
                except Exception as e: logger.error(f"Unexpected error encrypting session audit log: {e}", exc_info=True)
            elif self.master_key is None: logger.warning("Master key not set. Skipping encryption of session audit log.")

        # Save wrapped session key
        if self.master_key and self.current_session_key:
            wrapped_key_path = os.path.join(self.current_session_dir, "session_key.ek")
            try:
                wrapped_key = wrap_session_key(self.current_session_key, self.master_key)
                with open(wrapped_key_path, 'wb') as f: f.write(wrapped_key) # Can raise IOError/OSError
                logger.info(f"Wrapped session key saved to: {wrapped_key_path}")
                if self.audit_logger: self.audit_logger.log_action("SESSION_KEY_WRAPPED_AND_SAVED", {"path": wrapped_key_path})
            except (IOError, OSError) as e:
                logger.error(f"I/O error wrapping and saving session key: {e}", exc_info=True)
                if self.audit_logger: self.audit_logger.log_action("SESSION_KEY_WRAPPING_IO_FAILED", {"error": str(e)})
            except ValueError as e: # From wrap_session_key
                logger.error(f"Value error wrapping session key: {e}", exc_info=True)
                if self.audit_logger: self.audit_logger.log_action("SESSION_KEY_WRAPPING_VALUE_ERROR", {"error": str(e)})
            except Exception as e: # Fallback (e.g. cryptography exceptions if any)
                logger.error(f"Unexpected error wrapping and saving session key: {e}", exc_info=True)
                if self.audit_logger: self.audit_logger.log_action("SESSION_KEY_WRAPPING_FAILED", {"error": str(e)})

        if self.audit_logger: self.audit_logger.log_action("SESSION_STOP", {"session_id": self.current_session_id})

        if metadata_content :
            logger.info("Displaying session summary dialog...")
            summary_dialog = SessionSummaryDialog(metadata_dict=metadata_content, parent=self)
            summary_dialog.exec_()
            if self.audit_logger: self.audit_logger.log_action("SESSION_SUMMARY_DISPLAYED", {"session_id": self.current_session_id})
            logger.info("Session summary dialog closed.")
        else: logger.warning("Metadata content was not available, not displaying session summary dialog.")

        initial_status = "Eden Recorder: Ready to record. Click 'Record' to start."
        if self.master_key is None: initial_status += " (Encryption DISABLED)"
        else: initial_status += " (Encryption ENABLED)"
        self.status_label.setText(initial_status)
        self.record_button.setEnabled(True); self.stop_button.setEnabled(False)
        self.emotion_label.setText("Emotion: ---")
        self.transcript_widget.clear_transcript()
        self._reset_session_specific_vars()
        logger.info("Session cleanup and UI reset after stop.")

    def _reset_session_specific_vars(self): # No direct I/O, internal state cleanup
        logger.debug("Resetting session specific variables.")
        # ... (content as before)
        self.current_session_id = None; self.current_session_dir = None
        self.current_session_standard_dir = None; self.current_session_encrypted_dir = None
        self.current_session_key = None; self.audit_logger = None
        self.session_consent_status = None; self.session_consent_timestamp = None
        self.session_consent_expiry = None; self.session_stop_timestamp = None
        self.full_raw_transcript_segments.clear(); self.full_redacted_transcript_segments.clear()
        self.session_phi_pii_details.clear(); self.session_phi_pii_audio_mute_segments.clear()
        self.session_emotion_annotations.clear(); self.ai_training_consents.clear()
        self.session_voice_prints.clear(); self.session_voice_print_filepaths.clear()
        if self.diarization_result_queue: self.diarization_result_queue = None
        if self.emotion_results_queue: self.emotion_results_queue = None
        logger.debug("Session variables reset.")

    def closeEvent(self, event): # No direct I/O, mostly state and timer management
        logger.info("Close event triggered for MainApp.")
        # ... (content as before)
        if self.stop_button.isEnabled():
            logger.info("Stop button was enabled, calling _on_stop_button_clicked before closing.")
            self._on_stop_button_clicked()

        if self.general_audit_logger: self.general_audit_logger.log_action("APP_SHUTDOWN")
        else: logger.warning("General audit logger not available during shutdown.")

        logger.debug("Stopping timers.")
        if hasattr(self, 'diarization_update_timer') and self.diarization_update_timer.isActive(): self.diarization_update_timer.stop()
        if hasattr(self, 'text_processing_timer') and self.text_processing_timer.isActive(): self.text_processing_timer.stop()
        if hasattr(self, 'emotion_update_timer') and self.emotion_update_timer.isActive(): self.emotion_update_timer.stop()
        if hasattr(self, 'vu_meter') and self.vu_meter and self.vu_meter.timer.isActive(): self.vu_meter.timer.stop()
        if hasattr(self, 'transcript_widget') and self.transcript_widget and self.transcript_widget.timer.isActive(): self.transcript_widget.timer.stop()

        logger.info("Application shutdown process complete. Accepting close event.")
        event.accept()

if __name__ == '__main__':
    logger.info(f"Application starting with configuration: {config}")
    app = QApplication(sys.argv)
    try:
        main_window = MainApp()
        main_window.show()
        logger.info("Main window shown. Starting application event loop.")
        exit_code = app.exec_()
        logger.info(f"Application event loop finished with exit code: {exit_code}")
        sys.exit(exit_code)
    except Exception as e: # This top-level exception remains broad as it's the final catch-all
        logger.critical(f"Unhandled exception at top level: {e}", exc_info=True)
        print(f"CRITICAL_ERROR_UNHANDLED: {e}", file=sys.stderr)
        sys.exit(1)
