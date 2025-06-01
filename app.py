import sys
import re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox
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
from speech_emotion_recognizer import SpeechEmotionRecognizer # Import SER
from datetime import datetime, timedelta

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.session_consent_status = None
        self.session_consent_timestamp = None
        self.session_consent_expiry = None

        self.audio_recorder = None
        self.live_transcriber = None
        self.live_diarizer = None
        self.text_redactor = TextRedactor()
        self.speech_emotion_recognizer = None # Initialize SER

        self.current_speaker_label = "SPEAKER_UKN"
        self.diarization_result_queue = None
        self.emotion_results_queue = None # Queue for SER results

        self.session_voice_prints = {}
        self.session_phi_pii_details = []
        self.session_phi_pii_audio_mute_segments = []
        self.session_emotion_annotations = [] # Store (time, label, score, all_preds)

        self.redacted_text_queue = queue.Queue()

        self._init_ui() # Initializes UI elements including self.emotion_label

        self.diarization_update_timer = QTimer(self)
        self.diarization_update_timer.timeout.connect(self._update_current_speaker)
        self.diarization_update_timer.setInterval(200)

        self.text_processing_timer = QTimer(self)
        self.text_processing_timer.timeout.connect(self._process_transcribed_data)
        self.text_processing_timer.setInterval(100)

        self.emotion_update_timer = QTimer(self) # Timer for SER UI updates
        self.emotion_update_timer.timeout.connect(self._update_emotion_display)
        self.emotion_update_timer.setInterval(300) # Update emotion display e.g. every 300ms


    def _init_ui(self):
        self.setWindowTitle("Eden Recorder")
        self.setGeometry(100, 100, 500, 500) # Adjusted height for emotion label
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Eden Recorder: Ready to record. Click 'Record' to start.")
        layout.addWidget(self.status_label)
        self.vu_meter = VUMeterWidget()
        layout.addWidget(self.vu_meter)
        self.transcript_widget = LiveTranscriptWidget(transcript_text_queue=self.redacted_text_queue)
        layout.addWidget(self.transcript_widget)

        self.emotion_label = QLabel("Emotion: ---") # Initialize emotion label
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
        # ... (consent logic unchanged)
        print("Record button clicked.")
        if not self.run_consent_procedure():
            QMessageBox.warning(self, "Consent Required", "Recording cannot start.")
            self.status_label.setText("Consent denied. Recording not started. Ready to record.")
            return

        if self.session_consent_status:
            print("Consent given, proceeding.")
            # Clear all session data
            self.session_voice_prints = {}
            self.session_phi_pii_details = []
            self.session_phi_pii_audio_mute_segments = []
            self.session_emotion_annotations = [] # Clear emotion annotations
            self.current_speaker_label = "SPEAKER_UKN"
            self.emotion_label.setText("Emotion: ---") # Reset emotion label

            # Clear queues
            while not self.redacted_text_queue.empty(): self.redacted_text_queue.get()
            if self.diarization_result_queue:
                while not self.diarization_result_queue.empty(): self.diarization_result_queue.get()
            if self.emotion_results_queue: # Clear emotion queue if it exists
                 while not self.emotion_results_queue.empty(): self.emotion_results_queue.get()
            if self.live_transcriber and self.live_transcriber.get_transcribed_text_queue():
                 while not self.live_transcriber.get_transcribed_text_queue().empty():
                     self.live_transcriber.get_transcribed_text_queue().get()

            self.transcript_widget.clear_text()
            if hasattr(self.transcript_widget, 'set_current_speaker'):
                 self.transcript_widget.set_current_speaker(self.current_speaker_label)

            if self.audio_recorder is None: self.audio_recorder = AudioRecorder()
            self.audio_recorder.start_recording()

            if self.audio_recorder.is_recording:
                self.vu_meter.set_audio_chunk_queue(self.audio_recorder.get_audio_chunk_queue())
                transcription_audio_q = self.audio_recorder.get_transcription_audio_queue()

                self.live_transcriber = LiveTranscriber(audio_input_queue=transcription_audio_q, model_size="tiny")
                self.live_transcriber.start()
                self.text_processing_timer.start()

                if self.audio_recorder.samplerate == 0:
                     QMessageBox.critical(self, "Error", "Audio recorder sample rate 0.")
                     # ... (error handling for samplerate remains the same)
                     if self.live_transcriber: self.live_transcriber.stop(); self.live_transcriber = None
                     if self.text_processing_timer.isActive(): self.text_processing_timer.stop()
                     self.vu_meter.set_audio_chunk_queue(None)
                     if self.audio_recorder: self.audio_recorder.stop_recording(); self.audio_recorder = None
                     self.record_button.setEnabled(True); self.stop_button.setEnabled(False)
                     self.status_label.setText("Error: Audio sample rate unknown. Ready to record.")
                     return

                self.live_diarizer = LiveDiarizer(audio_input_queue=transcription_audio_q, sample_rate=self.audio_recorder.samplerate)
                self.diarization_result_queue = self.live_diarizer.get_diarization_result_queue()
                self.live_diarizer.start()
                self.diarization_update_timer.start()

                # Setup and start SpeechEmotionRecognizer
                self.speech_emotion_recognizer = SpeechEmotionRecognizer(
                    audio_input_queue=transcription_audio_q, # Uses the same raw audio queue
                    sample_rate=self.audio_recorder.samplerate
                )
                self.emotion_results_queue = self.speech_emotion_recognizer.get_emotion_results_queue()
                self.speech_emotion_recognizer.start()
                self.emotion_update_timer.start()

                self.record_button.setEnabled(False); self.stop_button.setEnabled(True)
                self.status_label.setText("Eden is Listening: Recording, Transcribing, Diarizing, Emotion Rec. & Redacting Text...") # Updated status
                print("All systems started.")
            # ... (else for audio_recorder.is_recording error handling remains)
            else:
                QMessageBox.critical(self, "Error", "Could not start audio recording.")
                self.status_label.setText("Error: Could not start audio recording. Ready to record.")
                self.audio_recorder = None
        # ... (else for session_consent_status remains)
        else:
             QMessageBox.information(self, "Consent Denied", "Not consented.")
             self.status_label.setText("Consent not given. Ready to record.")

    def _map_pii_chars_to_audio_time(self, pii_entity, word_timestamps, segment_text):
        # ... (no changes to this method)
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
        # ... (no changes to this method)
        if self.live_transcriber and self.live_transcriber.get_transcribed_text_queue():
            try:
                while not self.live_transcriber.get_transcribed_text_queue().empty():
                    raw_text_segment, word_timestamps = self.live_transcriber.get_transcribed_text_queue().get_nowait()
                    if raw_text_segment:
                        redacted_text, pii_entities = self.text_redactor.redact_text(raw_text_segment)
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
        # ... (no changes to this method)
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

    def _update_emotion_display(self): # New method
        if self.emotion_results_queue:
            latest_emotion_label = None
            latest_score = 0.0
            processed_item = False
            try:
                while not self.emotion_results_queue.empty():
                    timestamp, emotion_label, score, all_preds = self.emotion_results_queue.get_nowait()
                    self.session_emotion_annotations.append((timestamp, emotion_label, score, all_preds))
                    # Display the latest emotion received in this batch
                    latest_emotion_label = emotion_label
                    latest_score = score
                    processed_item = True

                if processed_item and latest_emotion_label is not None: # Update UI with the last emotion of the batch
                    self.emotion_label.setText(f"Emotion: {latest_emotion_label} (Score: {latest_score:.2f})")
                    # print(f"Emotion updated: {latest_emotion_label} @ {latest_score:.2f}") # Debug
            except queue.Empty:
                pass # No new emotion data
            except Exception as e:
                print(f"Error updating emotion display: {e}")


    def _on_stop_button_clicked(self):
        print("Stop button clicked.")
        was_recording = self.audio_recorder and self.audio_recorder.is_recording

        if self.text_processing_timer.isActive(): self.text_processing_timer.stop()
        if self.diarization_update_timer.isActive(): self.diarization_update_timer.stop()
        if self.emotion_update_timer.isActive(): self.emotion_update_timer.stop() # Stop SER timer

        if self.speech_emotion_recognizer: # Stop SER
            self.speech_emotion_recognizer.stop(); self.speech_emotion_recognizer = None; self.emotion_results_queue = None
            print("SpeechEmotionRecognizer stopped.")
            self.emotion_label.setText("Emotion: ---") # Reset emotion label

        if self.live_diarizer:
            self.live_diarizer.stop(); self.live_diarizer = None; self.diarization_result_queue = None
            print("LiveDiarizer stopped.")
        if self.live_transcriber:
            self._process_transcribed_data()
            self.live_transcriber.stop(); self.live_transcriber = None
            print("LiveTranscriber stopped.")
        self._process_transcribed_data()

        original_audio_saved = False; redacted_audio_saved = False
        if self.audio_recorder:
            if self.audio_recorder.is_recording :
                 original_audio_filename = "session_audio.wav"
                 self.audio_recorder.stop_recording(output_filename=original_audio_filename)
                 print(f"Original audio saved to {original_audio_filename}")
                 original_audio_saved = True
                 if self.session_phi_pii_audio_mute_segments:
                     try:
                         redacted_audio_filename = "session_audio_redacted.wav"
                         self.audio_recorder.save_redacted_audio(
                             output_filename=redacted_audio_filename,
                             mute_segments_time_list=self.session_phi_pii_audio_mute_segments)
                         print(f"Redacted audio saved to {redacted_audio_filename}.")
                         redacted_audio_saved = True
                     except Exception as e: print(f"Error saving redacted audio: {e}"); QMessageBox.warning(self, "Redaction Error", f"Failed to save redacted audio: {e}")
                 elif was_recording: print("No PII segments for audio redaction.")
            self.audio_recorder = None

        self.current_speaker_label = "SPEAKER_UKN"
        if hasattr(self.transcript_widget, 'set_current_speaker'): self.transcript_widget.set_current_speaker(None)
        self.vu_meter.set_audio_chunk_queue(None)
        self.vu_meter.current_rms_level = 0.0; self.vu_meter.max_rms_level = 0.001; self.vu_meter.update()

        # Summaries
        if was_recording:
            print(f"\n--- Session Summary ---")
            print(f"Voice Prints: {len(self.session_voice_prints)} speakers, {sum(len(v) for v in self.session_voice_prints.values())} total prints.")
            print(f"PII/PHI Text Instances: {len(self.session_phi_pii_details)}.")
            print(f"PII Audio Mute Segments: {len(self.session_phi_pii_audio_mute_segments)}.")
            print(f"Emotion Annotations: {len(self.session_emotion_annotations)} chunks analyzed.")
            if self.session_emotion_annotations:
                # Example: print last emotion or most frequent
                last_emotion = self.session_emotion_annotations[-1]
                print(f"  Last detected emotion chunk: {last_emotion[1]} @ {last_emotion[0]:.2f}s (Score: {last_emotion[2]:.2f})")

        # Reset session data
        self.session_voice_prints = {}; self.session_phi_pii_details = []; self.session_phi_pii_audio_mute_segments = []; self.session_emotion_annotations = []

        self.record_button.setEnabled(True); self.stop_button.setEnabled(False)
        status_parts = ["Session ended."]
        if original_audio_saved: status_parts.append("Original audio saved.")
        if redacted_audio_saved: status_parts.append("Redacted audio saved.")
        status_parts.append("Ready for new session.")
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
