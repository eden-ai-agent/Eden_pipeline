import sys
import re
import os
import numpy as np
import json
from datetime import datetime, timezone
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QDialog, QLineEdit
)
from PyQt5.QtCore import QTimer
import queue

from consent_dialog import ConsentDialog
from audio_capture import AudioRecorder
from vu_meter_widget import VUMeterWidget
from live_transcriber import LiveTranscriber
from live_transcript_widget import LiveTranscriptWidget
from live_diarizer import LiveDiarizer
from text_redactor import TextRedactor
from speech_emotion_recognizer import SpeechEmotionRecognizer
from encryption_utils import generate_aes_key, wrap_session_key, encrypt_file, derive_key_from_password, SALT
from ai_training_consent_dialog import AITrainingConsentDialog
from session_summary_dialog import SessionSummaryDialog
from metadata_viewer_dialog import MetadataViewerDialog # Import MetadataViewerDialog

# --- Password Dialog ---
class PasswordDialog(QDialog):
    # ... (PasswordDialog class remains unchanged)
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
            if not password: QMessageBox.warning(self, "Empty Password", "Password cannot be empty. Encryption will be disabled."); return None
            return password
        return None

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        # ... (all other initializations remain unchanged)
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
        self.base_output_dir = "sessions_output"; self.current_session_id = None
        self.current_session_dir = None; self.current_session_standard_dir = None
        self.current_session_encrypted_dir = None; self.current_session_key = None
        self.master_key = None
        self.general_audit_logger = None
        self.audit_logger = None
        self._setup_audit_loggers()
        self._setup_master_key()
        self._init_ui() # This will now also init the view metadata button
        if self.general_audit_logger: self.general_audit_logger.log_action("APP_STARTUP_COMPLETE", {"encryption_enabled": self.master_key is not None})
        self.diarization_update_timer = QTimer(self); self.diarization_update_timer.timeout.connect(self._update_current_speaker); self.diarization_update_timer.setInterval(200)
        self.text_processing_timer = QTimer(self); self.text_processing_timer.timeout.connect(self._process_transcribed_data); self.text_processing_timer.setInterval(100)
        self.emotion_update_timer = QTimer(self); self.emotion_update_timer.timeout.connect(self._update_emotion_display); self.emotion_update_timer.setInterval(300)

    def _setup_audit_loggers(self):
        # ... (remains unchanged)
        app_log_dir = "logs"
        os.makedirs(app_log_dir, exist_ok=True)
        self.general_audit_logger = AuditLogger(os.path.join(app_log_dir, "application_events.log"))

    def _setup_master_key(self):
        # ... (remains unchanged)
        dialog = PasswordDialog(self)
        user_password = dialog.get_password()
        if user_password:
            self.master_key = derive_key_from_password(user_password, salt=SALT)
            if self.general_audit_logger: self.general_audit_logger.log_action("MASTER_KEY_DERIVED", {"derivation_method": "PBKDF2-SHA256"})
        else:
            self.master_key = None
            if self.general_audit_logger: self.general_audit_logger.log_action("MASTER_KEY_NOT_PROVIDED", {"encryption_status": "disabled"})
            QMessageBox.warning(self, "Encryption Disabled", "No master password provided or it was empty. File encryption will be disabled.")

    def _init_ui(self):
        self.setWindowTitle("Eden Recorder"); self.setGeometry(100, 100, 500, 550) # Slightly increased height for new button
        layout = QVBoxLayout(self)
        initial_status = "Eden Recorder: Ready to record. Click 'Record' to start."
        if self.master_key is None: initial_status += " (Encryption DISABLED)"
        else: initial_status += " (Encryption ENABLED)"
        self.status_label = QLabel(initial_status); layout.addWidget(self.status_label)
        self.vu_meter = VUMeterWidget(); layout.addWidget(self.vu_meter)
        self.transcript_widget = LiveTranscriptWidget(transcript_text_queue=self.redacted_text_queue); layout.addWidget(self.transcript_widget)
        self.emotion_label = QLabel("Emotion: ---"); layout.addWidget(self.emotion_label)

        # Main control buttons
        main_button_layout = QHBoxLayout()
        self.record_button = QPushButton("Record"); self.record_button.clicked.connect(self._on_record_button_clicked); main_button_layout.addWidget(self.record_button)
        self.stop_button = QPushButton("Stop"); self.stop_button.clicked.connect(self._on_stop_button_clicked); self.stop_button.setEnabled(False); main_button_layout.addWidget(self.stop_button)
        layout.addLayout(main_button_layout)

        # Utility/Global action buttons
        utility_button_layout = QHBoxLayout()
        self.view_metadata_button = QPushButton("View Session Metadata")
        self.view_metadata_button.clicked.connect(self.open_metadata_viewer)
        utility_button_layout.addWidget(self.view_metadata_button)
        utility_button_layout.addStretch(1) # Push button to the left
        layout.addLayout(utility_button_layout)

        self.setLayout(layout)

    def open_metadata_viewer(self):
        # Ensure base_output_dir exists, or QFileDialog might open in an unexpected place
        if not os.path.exists(self.base_output_dir):
            os.makedirs(self.base_output_dir, exist_ok=True)
            print(f"Created base output directory for metadata viewer: {self.base_output_dir}")

        dialog = MetadataViewerDialog(parent=self, initial_dir=self.base_output_dir)
        dialog.exec_() # Show as a modal dialog


    def run_consent_procedure(self):
        # ... (no changes)
        dialog = ConsentDialog(self)
        dialog.exec_()
        self.session_consent_status = dialog.get_consent_status()
        self.session_consent_timestamp = dialog.get_consent_timestamp()
        if self.session_consent_status and self.session_consent_timestamp:
            try: self.session_consent_expiry = self.session_consent_timestamp.replace(year=self.session_consent_timestamp.year + 1)
            except ValueError: self.session_consent_expiry = self.session_consent_timestamp.replace(year=self.session_consent_timestamp.year + 1, day=28)
        else: self.session_consent_expiry = None
        return self.session_consent_status

    def _on_record_button_clicked(self):
        # ... (method content largely unchanged, ensure audit logs are placed correctly) ...
        pass # For brevity, assuming internal logic is correct from prior steps

    def _map_pii_chars_to_audio_time(self, pii_entity, word_timestamps, segment_text):
        # ... (no changes)
        return None, None

    def _process_transcribed_data(self):
        # ... (no changes)
        pass

    def _update_current_speaker(self):
        # ... (no changes)
        pass

    def _update_emotion_display(self):
        # ... (no changes)
        pass

    def _save_and_encrypt_voice_embeddings(self):
        # ... (no changes)
        return False, False

    def _generate_metadata_dict(self) -> dict:
        # ... (no changes)
        return {} # Placeholder

    def _on_stop_button_clicked(self):
        # ... (method content largely unchanged until the end) ...
        # ... (all file saving, encryption, AI consent dialogs happen before this) ...

        metadata_content = self._generate_metadata_dict() # Generate metadata

        metadata_saved, metadata_encrypted = False, False # Initialize flags
        if self.current_session_standard_dir and metadata_content:
            standard_metadata_path = os.path.join(self.current_session_standard_dir, "metadata.json")
            try:
                with open(standard_metadata_path, 'w', encoding='utf-8') as f: json.dump(metadata_content, f, indent=4)
                print(f"Metadata saved to {standard_metadata_path}"); metadata_saved = True
                if self.audit_logger: self.audit_logger.log_action("FILE_SAVED_STANDARD", {"type": "metadata_json", "path": standard_metadata_path})
                if self.master_key and self.current_session_key:
                    encrypted_metadata_path = os.path.join(self.current_session_encrypted_dir, "metadata.json.enc")
                    try:
                        encrypt_file(standard_metadata_path, self.current_session_key, encrypted_metadata_path)
                        print(f"Encrypted metadata saved to {encrypted_metadata_path}"); metadata_encrypted = True
                        if self.audit_logger: self.audit_logger.log_action("FILE_ENCRYPTED", {"type": "metadata_json", "path": encrypted_metadata_path})
                    except Exception as e: print(f"Error encrypting metadata.json: {e}"); # Log error
                elif self.master_key is None and metadata_saved: print("Master key not set. Skipping encryption of metadata.json.")
            except Exception as e: print(f"Error saving metadata.json: {e}"); # Log error

        # ... (encrypt audit log, save wrapped session key as before) ...
        # ... (clear session data as before) ...
        # ... (update status label as before) ...

        # Display Session Summary Dialog (This is the new part)
        if metadata_content and (self.audio_recorder and (self.audio_recorder.is_recording or self.audio_recorder.frames)): # Ensure session was active
            print("Displaying session summary dialog...")
            summary_dialog = SessionSummaryDialog(metadata_dict=metadata_content, parent=self)
            summary_dialog.exec_()
            if self.audit_logger: self.audit_logger.log_action("SESSION_SUMMARY_DISPLAYED", {"session_id": self.current_session_id})


    def closeEvent(self, event):
        # ... (no changes)
        print("Close event triggered for MainApp.")
        if self.stop_button.isEnabled(): self._on_stop_button_clicked()
        if self.general_audit_logger: self.general_audit_logger.log_action("APP_SHUTDOWN")
        if self.diarization_update_timer.isActive(): self.diarization_update_timer.stop()
        if self.text_processing_timer.isActive(): self.text_processing_timer.stop()
        if self.emotion_update_timer.isActive(): self.emotion_update_timer.stop()
        if self.vu_meter and self.vu_meter.timer.isActive(): self.vu_meter.timer.stop()
        if self.transcript_widget and self.transcript_widget.timer.isActive(): self.transcript_widget.timer.stop()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainApp()
    main_window.show()
    sys.exit(app.exec_())
