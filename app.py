import sys
import re
import os
import numpy as np
import json # For saving metadata
from datetime import datetime
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

# --- Password Dialog ---
class PasswordDialog(QDialog):
    # ... (PasswordDialog class remains unchanged)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Master Password Required")
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.info_label = QLabel("Enter Master Password for Encryption:")
        layout.addWidget(self.info_label)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.setMinimumWidth(300)

    def get_password(self):
        if self.exec_() == QDialog.Accepted:
            password = self.password_input.text()
            if not password:
                QMessageBox.warning(self, "Empty Password", "Password cannot be empty. Encryption will be disabled.")
                return None
            return password
        return None

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        # ... (other session variables)
        self.session_consent_status = None
        self.session_consent_timestamp = None
        self.session_stop_timestamp = None
        self.session_consent_expiry = None

        self.audio_recorder = None
        self.live_transcriber = None
        self.live_diarizer = None
        self.text_redactor = TextRedactor()
        self.speech_emotion_recognizer = None

        self.current_speaker_label = "SPEAKER_UKN"
        self.diarization_result_queue = None
        self.emotion_results_queue = None

        self.session_voice_prints = {}
        self.session_voice_print_filepaths = {}
        self.session_phi_pii_details = []
        self.session_phi_pii_audio_mute_segments = []
        self.session_emotion_annotations = []
        self.full_raw_transcript_segments = []
        self.full_redacted_transcript_segments = []
        self.ai_training_consents = {}

        self.redacted_text_queue = queue.Queue()

        self.base_output_dir = "sessions_output"
        self.current_session_id = None
        self.current_session_dir = None
        self.current_session_standard_dir = None
        self.current_session_encrypted_dir = None
        self.current_session_key = None

        self.master_key = None
        self._setup_master_key()

        self._init_ui()

        # ... (timers setup)
        self.diarization_update_timer = QTimer(self)
        self.diarization_update_timer.timeout.connect(self._update_current_speaker)
        self.diarization_update_timer.setInterval(200)
        self.text_processing_timer = QTimer(self)
        self.text_processing_timer.timeout.connect(self._process_transcribed_data)
        self.text_processing_timer.setInterval(100)
        self.emotion_update_timer = QTimer(self)
        self.emotion_update_timer.timeout.connect(self._update_emotion_display)
        self.emotion_update_timer.setInterval(300)

    def _setup_master_key(self):
        # ... (remains unchanged)
        dialog = PasswordDialog(self)
        user_password = dialog.get_password()
        if user_password:
            self.master_key = derive_key_from_password(user_password, salt=SALT)
            print("Master key derived from password. File encryption will be enabled.")
        else:
            self.master_key = None
            print("No valid password provided or dialog cancelled. Encryption will be disabled for this session.")
            QMessageBox.warning(self, "Encryption Disabled",
                                "No master password was provided or it was empty. File encryption will be disabled.")

    def _init_ui(self):
        # ... (UI setup largely the same, status label updated)
        self.setWindowTitle("Eden Recorder")
        self.setGeometry(100, 100, 500, 500)
        layout = QVBoxLayout(self)
        initial_status = "Eden Recorder: Ready to record. Click 'Record' to start."
        if self.master_key is None: initial_status += " (Encryption DISABLED)"
        else: initial_status += " (Encryption ENABLED)"
        self.status_label = QLabel(initial_status)
        layout.addWidget(self.status_label)
        self.vu_meter = VUMeterWidget()
        layout.addWidget(self.vu_meter)
        self.transcript_widget = LiveTranscriptWidget(transcript_text_queue=self.redacted_text_queue)
        layout.addWidget(self.transcript_widget)
        self.emotion_label = QLabel("Emotion: ---")
        layout.addWidget(self.emotion_label)
        button_layout = QHBoxLayout()
        self.record_button = QPushButton("Record")
        self.record_button.clicked.connect(self._on_record_button_clicked)
        button_layout.addWidget(self.record_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self._on_stop_button_clicked)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)

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
        # ... (consent & directory creation unchanged)
        print("Record button clicked.")
        if not self.run_consent_procedure():
            QMessageBox.warning(self, "Consent Required", "Recording cannot start.")
            base_msg = "Consent denied. Recording not started."
            self.status_label.setText(f"{base_msg} {'Encryption ENABLED.' if self.master_key else 'Encryption DISABLED.'} Ready to record.")
            return

        if self.session_consent_status:
            print("Consent given, proceeding.")
            self.current_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_session_dir = os.path.join(self.base_output_dir, self.current_session_id)
            self.current_session_standard_dir = os.path.join(self.current_session_dir, "standard")
            self.current_session_encrypted_dir = os.path.join(self.current_session_dir, "encrypted")
            try:
                os.makedirs(self.current_session_standard_dir, exist_ok=True)
                if self.master_key:
                    os.makedirs(self.current_session_encrypted_dir, exist_ok=True)
                print(f"Session directories created: {self.current_session_standard_dir}")
            except OSError as e:
                QMessageBox.critical(self, "Directory Error", f"Could not create session directories: {e}")
                self.status_label.setText(f"Error: Failed to create session directories. {'Encryption ENABLED.' if self.master_key else 'Encryption DISABLED.'} Ready to record.")
                return

            if self.master_key:
                self.current_session_key = generate_aes_key()
                print(f"Generated new session key for session {self.current_session_id}")
            else:
                self.current_session_key = None
                print("Master key not set. Session files will not be encrypted.")

            self.session_voice_prints = {}; self.session_voice_print_filepaths = {}
            self.session_phi_pii_details = []
            self.session_phi_pii_audio_mute_segments = []; self.session_emotion_annotations = []
            self.full_raw_transcript_segments.clear(); self.full_redacted_transcript_segments.clear()
            self.ai_training_consents = {}; self.current_speaker_label = "SPEAKER_UKN"; self.emotion_label.setText("Emotion: ---")

            while not self.redacted_text_queue.empty(): self.redacted_text_queue.get()
            # ... (clear other queues) ...

            self.transcript_widget.clear_text()
            if hasattr(self.transcript_widget, 'set_current_speaker'):
                 self.transcript_widget.set_current_speaker(self.current_speaker_label)

            if self.audio_recorder is None: self.audio_recorder = AudioRecorder()
            self.audio_recorder.start_recording()

            if self.audio_recorder.is_recording:
                # ... (start components) ...
                self.status_label.setText("Eden is Listening: Recording, Transcribing, Diarizing, Emotion Rec. & Redacting Text..." + (" (ENCRYPTION DISABLED)" if self.master_key is None else ""))
                print("All systems started.")
            # ... (error handling for components remains)
            else:
                QMessageBox.critical(self, "Error", "Could not start audio recording.")
                self.status_label.setText(f"Error: Could not start audio recording. {'Encryption ENABLED.' if self.master_key else 'Encryption DISABLED.'} Ready to record.")
                self.audio_recorder = None
        else:
             QMessageBox.information(self, "Consent Denied", "Not consented.")
             self.status_label.setText(f"Consent not given. {'Encryption ENABLED.' if self.master_key else 'Encryption DISABLED.'} Ready to record.")


    def _map_pii_chars_to_audio_time(self, pii_entity, word_timestamps, segment_text):
        # ... (no changes)
        pii_start_char = pii_entity['start']
        pii_end_char = pii_entity['end']
        found_audio_start, found_audio_end = None, None
        current_char_offset = 0
        first_word_in_pii_found = False
        for word_info in word_timestamps:
            word_text = word_info['word']
            try:
                word_char_start_in_segment = segment_text.find(word_text, current_char_offset)
                if word_char_start_in_segment == -1: word_char_start_in_segment = current_char_offset
            except AttributeError: word_char_start_in_segment = current_char_offset
            word_char_end_in_segment = word_char_start_in_segment + len(word_text)
            overlap_starts = (pii_start_char >= word_char_start_in_segment and pii_start_char < word_char_end_in_segment)
            overlap_ends = (pii_end_char > word_char_start_in_segment and pii_end_char <= word_char_end_in_segment)
            word_spans_pii = (word_char_start_in_segment <= pii_start_char and word_char_end_in_segment >= pii_end_char)
            pii_spans_word = (pii_start_char <= word_char_start_in_segment and pii_end_char >= word_char_end_in_segment)
            is_part_of_pii = overlap_starts or overlap_ends or word_spans_pii or pii_spans_word
            if is_part_of_pii:
                if not first_word_in_pii_found:
                    found_audio_start = word_info['start']
                    first_word_in_pii_found = True
                found_audio_end = word_info['end']
            current_char_offset = word_char_end_in_segment
        if found_audio_start is not None and found_audio_end is not None: return found_audio_start, found_audio_end
        return None, None

    def _process_transcribed_data(self):
        # ... (no changes)
        if self.live_transcriber and self.live_transcriber.get_transcribed_text_queue():
            try:
                while not self.live_transcriber.get_transcribed_text_queue().empty():
                    raw_text_segment, word_timestamps = self.live_transcriber.get_transcribed_text_queue().get_nowait()
                    if raw_text_segment:
                        self.full_raw_transcript_segments.append(raw_text_segment)
                        redacted_text, pii_entities = self.text_redactor.redact_text(raw_text_segment)
                        self.full_redacted_transcript_segments.append(redacted_text)
                        if pii_entities:
                            self.session_phi_pii_details.extend(pii_entities)
                            for pii_entity in pii_entities:
                                audio_start, audio_end = self._map_pii_chars_to_audio_time(
                                    pii_entity, word_timestamps, raw_text_segment)
                                if audio_start is not None and audio_end is not None and audio_end > audio_start:
                                    self.session_phi_pii_audio_mute_segments.append((audio_start, audio_end))
                        self.redacted_text_queue.put(redacted_text)
            except queue.Empty: pass
            except Exception as e: print(f"Error in transcribed data processing: {e}")

    def _update_current_speaker(self):
        # ... (no changes)
        if self.diarization_result_queue:
            speaker_label_changed_in_batch = False
            try:
                while not self.diarization_result_queue.empty():
                    speaker_label, start_s, end_s, voice_embedding = self.diarization_result_queue.get_nowait()
                    if self.current_speaker_label != speaker_label:
                        self.current_speaker_label = speaker_label
                        speaker_label_changed_in_batch = True
                    if voice_embedding is not None and hasattr(voice_embedding, 'size') and voice_embedding.size > 0:
                        if speaker_label not in self.session_voice_prints: self.session_voice_prints[speaker_label] = []
                        self.session_voice_prints[speaker_label].append(voice_embedding)
                if speaker_label_changed_in_batch:
                    if hasattr(self.transcript_widget, 'set_current_speaker'):
                        self.transcript_widget.set_current_speaker(self.current_speaker_label)
            except queue.Empty: pass
            except Exception as e: print(f"Error updating speaker data: {e}")

    def _update_emotion_display(self):
        # ... (no changes)
        if self.emotion_results_queue:
            latest_emotion_label = None; latest_score = 0.0; processed_item = False
            try:
                while not self.emotion_results_queue.empty():
                    timestamp, emotion_label, score, all_preds = self.emotion_results_queue.get_nowait()
                    self.session_emotion_annotations.append((timestamp, emotion_label, score, all_preds))
                    latest_emotion_label = emotion_label; latest_score = score; processed_item = True
                if processed_item and latest_emotion_label is not None:
                    self.emotion_label.setText(f"Emotion: {latest_emotion_label} (Score: {latest_score:.2f})")
            except queue.Empty: pass
            except Exception as e: print(f"Error updating emotion display: {e}")

    def _save_and_encrypt_voice_embeddings(self):
        # ... (no changes)
        if not self.current_session_standard_dir or not self.session_voice_prints: return False
        standard_embeddings_dir = os.path.join(self.current_session_standard_dir, "voice_embeddings")
        os.makedirs(standard_embeddings_dir, exist_ok=True)
        encrypted_embeddings_dir = None
        if self.master_key and self.current_session_key:
            encrypted_embeddings_dir = os.path.join(self.current_session_encrypted_dir, "voice_embeddings")
            os.makedirs(encrypted_embeddings_dir, exist_ok=True)
        self.session_voice_print_filepaths.clear(); embeddings_saved_count = 0; any_embedding_encrypted = False
        for speaker_label, embeddings_list in self.session_voice_prints.items():
            self.session_voice_print_filepaths[speaker_label] = []
            for i, embedding_array in enumerate(embeddings_list):
                embedding_filename = f"{speaker_label}_emb_{i}.npy"
                standard_embedding_path = os.path.join(standard_embeddings_dir, embedding_filename)
                relative_path = os.path.join("standard", "voice_embeddings", embedding_filename)
                try:
                    np.save(standard_embedding_path, embedding_array)
                    self.session_voice_print_filepaths[speaker_label].append(relative_path); embeddings_saved_count +=1
                    if encrypted_embeddings_dir and self.current_session_key:
                        encrypted_embedding_path = os.path.join(encrypted_embeddings_dir, embedding_filename + ".enc")
                        try: encrypt_file(standard_embedding_path, self.current_session_key, encrypted_embedding_path); any_embedding_encrypted = True
                        except Exception as e: print(f"Error encrypting embedding {standard_embedding_path}: {e}")
                except Exception as e: print(f"Error saving embedding {standard_embedding_path}: {e}")
        if embeddings_saved_count > 0: print(f"Saved {embeddings_saved_count} voice embeddings for {len(self.session_voice_prints)} speakers.")
        return embeddings_saved_count > 0, any_embedding_encrypted


    def _generate_metadata_dict(self) -> dict:
        # ... (no changes to this method's internal logic from previous step)
        if not self.current_session_id: return {}
        metadata = {
            'session_id': self.current_session_id,
            'session_start_time': self.session_consent_timestamp.isoformat() if self.session_consent_timestamp else None,
            'session_end_time': self.session_stop_timestamp.isoformat() if self.session_stop_timestamp else None,
            'encryption_status': {
                'master_key_provided': self.master_key is not None,
                'session_key_generated': self.current_session_key is not None,
                'files_encrypted': (self.master_key and self.current_session_key) is not None
            },
            'initial_recording_consent': {
                'consent_given': self.session_consent_status,
                'timestamp': self.session_consent_timestamp.isoformat() if self.session_consent_timestamp else None,
                'expires_timestamp': self.session_consent_expiry.isoformat() if self.session_consent_expiry else None
            },
            'ai_training_consent_per_speaker': self.ai_training_consents if self.ai_training_consents else "No speakers identified or consent not solicited.",
            'diarization_summary': {
                'speakers_identified': list(self.session_voice_print_filepaths.keys()),
                'num_voice_prints_collected_per_speaker': { k: len(v) for k, v in self.session_voice_print_filepaths.items()}
            },
            'voice_print_file_references': self.session_voice_print_filepaths,
            'phi_pii_detected_in_transcript': self.session_phi_pii_details,
            'phi_pii_audio_mute_segments': [{'start_time_seconds': s, 'end_time_seconds': e} for s, e in self.session_phi_pii_audio_mute_segments],
            'emotion_annotations': [{'segment_start_time_seconds': emo[0], 'dominant_emotion': emo[1], 'score': emo[2], 'all_predictions': emo[3] } for emo in self.session_emotion_annotations],
            'file_manifest': [],
            'audit_log_file_references': "TODO: Implement audit log path"
        }
        session_root_dir = self.current_session_dir
        def add_file_to_manifest(filename_in_standard, description, is_encrypted_version_expected):
            # ... (file manifest helper logic unchanged) ...
            rel_path_standard = os.path.join("standard", filename_in_standard)
            full_path_standard = os.path.join(self.current_session_standard_dir, filename_in_standard)
            entry = None
            if os.path.exists(full_path_standard):
                entry = {'filename': filename_in_standard, 'path': rel_path_standard, 'description': description, 'encrypted_counterpart': None}
                if is_encrypted_version_expected and self.master_key and self.current_session_key:
                    rel_path_encrypted = os.path.join("encrypted", filename_in_standard + ".enc")
                    full_path_encrypted = os.path.join(self.current_session_encrypted_dir, filename_in_standard + ".enc")
                    if os.path.exists(full_path_encrypted): entry['encrypted_counterpart'] = rel_path_encrypted
                metadata['file_manifest'].append(entry)
        add_file_to_manifest("full_audio.wav", "Original full audio recording", True)
        add_file_to_manifest("redacted_audio.wav", "Audio recording with PII segments muted", True)
        add_file_to_manifest("transcript.txt", "Full raw transcript", True)
        add_file_to_manifest("redacted.txt", "Transcript with PII redacted", True)
        for speaker_label, paths_list in self.session_voice_print_filepaths.items():
            for rel_path_in_manifest in paths_list:
                emb_filename_only = os.path.basename(rel_path_in_manifest)
                emb_description = f"Voice embedding for {speaker_label}, segment {os.path.splitext(emb_filename_only)[0].split('_')[-1]}"
                enc_rel_path = rel_path_in_manifest.replace("standard/", "encrypted/", 1) + ".enc"
                full_enc_emb_path = os.path.join(session_root_dir, enc_rel_path)
                metadata['file_manifest'].append({'filename': emb_filename_only, 'path': rel_path_in_manifest, 'description': emb_description, 'encrypted_counterpart': enc_rel_path if (self.master_key and os.path.exists(full_enc_emb_path)) else None})
        if self.master_key and self.current_session_key:
            key_filename = "session_key.key.enc"
            key_rel_path = os.path.join("encrypted", key_filename)
            if os.path.exists(os.path.join(self.current_session_encrypted_dir, key_filename)):
                 metadata['file_manifest'].append({'filename': key_filename, 'path': key_rel_path, 'description': "Wrapped (encrypted) session encryption key", 'encrypted_counterpart': None })
        metadata['audit_log_file_references'] = "TODO: Implement audit log path and add to manifest."
        return metadata


    def _on_stop_button_clicked(self):
        print("Stop button clicked.")
        was_recording = self.audio_recorder and self.audio_recorder.is_recording
        self.session_stop_timestamp = datetime.now()

        if self.text_processing_timer.isActive(): self.text_processing_timer.stop()
        if self.diarization_update_timer.isActive(): self.diarization_update_timer.stop()
        if self.emotion_update_timer.isActive(): self.emotion_update_timer.stop()
        if self.speech_emotion_recognizer:
            self.speech_emotion_recognizer.stop(); self.speech_emotion_recognizer = None; self.emotion_results_queue = None
            print("SpeechEmotionRecognizer stopped."); self.emotion_label.setText("Emotion: ---")
        if self.live_diarizer:
            self.live_diarizer.stop(); self.live_diarizer = None; self.diarization_result_queue = None
            print("LiveDiarizer stopped.")
        if self.live_transcriber:
            self._process_transcribed_data()
            self.live_transcriber.stop(); self.live_transcriber = None
            print("LiveTranscriber stopped.")
        self._process_transcribed_data()

        original_audio_saved, redacted_audio_saved, encryption_performed_audio = False, False, False
        transcripts_saved, transcripts_encrypted = False, False
        embeddings_saved, embeddings_encrypted = False, False # Track embedding save/encryption

        if self.audio_recorder and (self.audio_recorder.is_recording or self.audio_recorder.frames) and self.current_session_standard_dir:
            # ... (audio saving and encryption logic as before) ...
            original_audio_filepath = os.path.join(self.current_session_standard_dir, "full_audio.wav")
            try:
                self.audio_recorder.stop_recording(output_filepath=original_audio_filepath)
                print(f"Original audio saved to {original_audio_filepath}"); original_audio_saved = True
                if self.master_key and self.current_session_key:
                    encrypted_orig_audio_path = os.path.join(self.current_session_encrypted_dir, "full_audio.wav.enc")
                    try: encrypt_file(original_audio_filepath, self.current_session_key, encrypted_orig_audio_path); print(f"Encrypted original audio saved to {encrypted_orig_audio_path}"); encryption_performed_audio = True
                    except Exception as e: print(f"Error encrypting original audio: {e}")
                elif self.master_key is None and original_audio_saved: print("Master key not available. Skipping encryption of original audio.")
                if self.session_phi_pii_audio_mute_segments:
                    redacted_audio_filepath = os.path.join(self.current_session_standard_dir, "redacted_audio.wav")
                    try:
                        self.audio_recorder.save_redacted_audio(output_filepath=redacted_audio_filepath, mute_segments_time_list=self.session_phi_pii_audio_mute_segments)
                        print(f"Redacted audio saved to {redacted_audio_filepath}."); redacted_audio_saved = True
                        if self.master_key and self.current_session_key:
                            encrypted_redacted_audio_path = os.path.join(self.current_session_encrypted_dir, "redacted_audio.wav.enc")
                            try: encrypt_file(redacted_audio_filepath, self.current_session_key, encrypted_redacted_audio_path); print(f"Encrypted redacted audio saved to {encrypted_redacted_audio_path}") # encryption_performed_audio already true if orig was enc.
                            except Exception as e: print(f"Error encrypting redacted audio: {e}")
                        elif self.master_key is None and redacted_audio_saved: print("Master key not available. Skipping encryption of redacted audio.")
                    except Exception as e: print(f"Error saving redacted audio: {e}")
                elif was_recording: print("No PII segments for audio redaction.")
            except Exception as e: print(f"Error during audio_recorder.stop_recording: {e}")

        if self.current_session_standard_dir: # Save transcripts
            # ... (transcript saving and encryption logic as before) ...
            full_raw_text = "\n".join(self.full_raw_transcript_segments)
            raw_transcript_path = os.path.join(self.current_session_standard_dir, "transcript.txt")
            try:
                with open(raw_transcript_path, 'w', encoding='utf-8') as f: f.write(full_raw_text)
                print(f"Raw transcript saved to {raw_transcript_path}"); transcripts_saved = True
                if self.master_key and self.current_session_key:
                    encrypted_raw_transcript_path = os.path.join(self.current_session_encrypted_dir, "transcript.txt.enc")
                    try: encrypt_file(raw_transcript_path, self.current_session_key, encrypted_raw_transcript_path); print(f"Encrypted raw transcript to {encrypted_raw_transcript_path}"); transcripts_encrypted = True
                    except Exception as e: print(f"Error encrypting raw transcript: {e}")
                elif self.master_key is None and transcripts_saved: print("Master key not available. Skipping encryption of raw transcript.")
            except Exception as e: print(f"Error saving raw transcript: {e}")
            full_redacted_text = "\n".join(self.full_redacted_transcript_segments)
            redacted_transcript_path = os.path.join(self.current_session_standard_dir, "redacted.txt")
            try:
                with open(redacted_transcript_path, 'w', encoding='utf-8') as f: f.write(full_redacted_text)
                print(f"Redacted transcript saved to {redacted_transcript_path}")
                if self.master_key and self.current_session_key:
                    encrypted_redacted_transcript_path = os.path.join(self.current_session_encrypted_dir, "redacted.txt.enc")
                    try: encrypt_file(redacted_transcript_path, self.current_session_key, encrypted_redacted_transcript_path); print(f"Encrypted redacted transcript to {encrypted_redacted_transcript_path}"); transcripts_encrypted = True
                    except Exception as e: print(f"Error encrypting redacted transcript: {e}")
                elif self.master_key is None and transcripts_saved: print("Master key not available. Skipping encryption of redacted transcript.")
            except Exception as e: print(f"Error saving redacted transcript: {e}")

        if self.session_voice_prints and self.current_session_standard_dir:
            embeddings_saved, embeddings_encrypted = self._save_and_encrypt_voice_embeddings()

        active_speaker_labels = list(self.session_voice_prints.keys())
        if active_speaker_labels: # AI Consent
            # ... (AI consent logic unchanged) ...
            consent_dialog = AITrainingConsentDialog(speaker_labels=active_speaker_labels, parent=self)
            if consent_dialog.exec_() == QDialog.Accepted: self.ai_training_consents = consent_dialog.get_collected_consents(); print(f"AI Training Consents collected: {self.ai_training_consents}")
            else: self.ai_training_consents = {label: False for label in active_speaker_labels}; print("AI Training Consent dialog cancelled."); QMessageBox.information(self, "AI Consent Skipped", "AI Training consent was not provided.")
        else: self.ai_training_consents = {}; print("No speakers identified. Skipping AI Training Consent dialog.")

        # Generate and Save Metadata
        metadata_content = self._generate_metadata_dict()
        metadata_saved = False; metadata_encrypted = False
        if self.current_session_standard_dir and metadata_content: # Ensure session dir and content exist
            standard_metadata_path = os.path.join(self.current_session_standard_dir, "metadata.json")
            try:
                with open(standard_metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata_content, f, indent=4)
                print(f"Metadata saved to {standard_metadata_path}")
                metadata_saved = True
                if self.master_key and self.current_session_key:
                    encrypted_metadata_path = os.path.join(self.current_session_encrypted_dir, "metadata.json.enc")
                    try:
                        encrypt_file(standard_metadata_path, self.current_session_key, encrypted_metadata_path)
                        print(f"Encrypted metadata saved to {encrypted_metadata_path}")
                        metadata_encrypted = True
                    except Exception as e: print(f"Error encrypting metadata.json: {e}")
                elif self.master_key is None and metadata_saved: print("Master key not set. Skipping encryption of metadata.json.")
            except Exception as e: print(f"Error saving metadata.json: {e}")

        # Wrap and save session key (if encryption was active for any file type)
        any_file_encrypted = encryption_performed_audio or transcripts_encrypted or embeddings_encrypted or metadata_encrypted
        if self.master_key and self.current_session_key and any_file_encrypted:
            try:
                wrapped_session_key = wrap_session_key(self.current_session_key, self.master_key)
                wrapped_key_path = os.path.join(self.current_session_encrypted_dir, "session_key.key.enc")
                with open(wrapped_key_path, 'wb') as f: f.write(wrapped_session_key)
                print(f"Wrapped session key saved to {wrapped_key_path}")
            except Exception as e: print(f"Error wrapping/saving session key: {e}")

        if self.audio_recorder: self.audio_recorder = None
        self.current_session_key = None

        self.current_speaker_label = "SPEAKER_UKN"
        if hasattr(self.transcript_widget, 'set_current_speaker'): self.transcript_widget.set_current_speaker(None)
        self.vu_meter.set_audio_chunk_queue(None)
        self.vu_meter.current_rms_level = 0.0; self.vu_meter.max_rms_level = 0.001; self.vu_meter.update()

        if was_recording: print(f"\n--- Session {self.current_session_id} Summary ---")

        self.session_voice_prints = {}; self.session_voice_print_filepaths = {}
        self.session_phi_pii_details = []; self.session_phi_pii_audio_mute_segments = []
        self.session_emotion_annotations = []; self.full_raw_transcript_segments.clear()
        self.full_redacted_transcript_segments.clear()
        # self.ai_training_consents is cleared at start of next recording

        self.record_button.setEnabled(True); self.stop_button.setEnabled(False)
        status_parts = ["Session ended."]
        if original_audio_saved: status_parts.append("Original audio saved.")
        if redacted_audio_saved: status_parts.append("Redacted audio saved.")
        if transcripts_saved: status_parts.append("Transcripts saved.")
        if embeddings_saved: status_parts.append("Embeddings saved.")
        if metadata_saved: status_parts.append("Metadata saved.")
        if any_file_encrypted : status_parts.append("Files encrypted.")
        elif self.master_key is None and (original_audio_saved or transcripts_saved or embeddings_saved or metadata_saved) :
            status_parts.append("Encryption skipped (no master key).")
        if self.ai_training_consents is not None and active_speaker_labels : status_parts.append("AI consent processed.")
        if self.current_session_id : status_parts.append(f"Session ID: {self.current_session_id}.")
        status_parts.append("Ready.")
        self.status_label.setText(" ".join(status_parts))
        print(" ".join(status_parts))

    def closeEvent(self, event):
        print("Close event triggered for MainApp.")
        self._on_stop_button_clicked()
        if self.vu_meter and self.vu_meter.timer.isActive(): self.vu_meter.timer.stop()
        if self.transcript_widget and self.transcript_widget.timer.isActive(): self.transcript_widget.timer.stop()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainApp()
    main_window.show()
    sys.exit(app.exec_())
