import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox
)
from PyQt5.QtCore import QTimer # Ensure QTimer is imported
import queue # Ensure queue is imported, for _update_current_speaker

from consent_dialog import ConsentDialog
from audio_capture import AudioRecorder
from vu_meter_widget import VUMeterWidget
from live_transcriber import LiveTranscriber
from live_transcript_widget import LiveTranscriptWidget
from live_diarizer import LiveDiarizer # Import LiveDiarizer
from datetime import datetime, timedelta

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.session_consent_status = None
        self.session_consent_timestamp = None
        self.session_consent_expiry = None

        self.audio_recorder = None
        self.live_transcriber = None
        self.live_diarizer = None # Initialize live_diarizer
        self.current_speaker_label = "SPEAKER_UKN" # Default speaker label
        self.diarization_result_queue = None

        self._init_ui()

        # Timer for diarization updates
        self.diarization_update_timer = QTimer(self)
        self.diarization_update_timer.timeout.connect(self._update_current_speaker)
        self.diarization_update_timer.setInterval(200) # Check for new speaker every 200ms

    def _init_ui(self):
        self.setWindowTitle("Eden Recorder")
        self.setGeometry(100, 100, 500, 450) # Adjusted height for more content

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Welcome! Click 'Record' to start.")
        layout.addWidget(self.status_label)

        self.vu_meter = VUMeterWidget()
        layout.addWidget(self.vu_meter)

        self.transcript_widget = LiveTranscriptWidget()
        layout.addWidget(self.transcript_widget)

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
        dialog = ConsentDialog(self)
        dialog.exec_()
        self.session_consent_status = dialog.get_consent_status()
        self.session_consent_timestamp = dialog.get_consent_timestamp()
        if self.session_consent_status and self.session_consent_timestamp:
            try:
                self.session_consent_expiry = self.session_consent_timestamp.replace(
                    year=self.session_consent_timestamp.year + 1)
            except ValueError:
                self.session_consent_expiry = self.session_consent_timestamp.replace(
                    year=self.session_consent_timestamp.year + 1, day=28)
        else:
            self.session_consent_expiry = None
        return self.session_consent_status

    def _on_record_button_clicked(self):
        print("Record button clicked.")
        if not self.run_consent_procedure():
            QMessageBox.warning(self, "Consent Required", "Recording cannot start without consent.")
            self.status_label.setText("Consent denied. Recording not started.")
            return

        if self.session_consent_status:
            print("Consent given, proceeding with recording.")
            if self.audio_recorder is None:
                self.audio_recorder = AudioRecorder()

            self.audio_recorder.start_recording()

            if self.audio_recorder.is_recording:
                audio_queue_vu = self.audio_recorder.get_audio_chunk_queue()
                self.vu_meter.set_audio_chunk_queue(audio_queue_vu)

                transcription_audio_q = self.audio_recorder.get_transcription_audio_queue()
                self.live_transcriber = LiveTranscriber(
                    audio_input_queue=transcription_audio_q, model_size="tiny")

                transcribed_text_q = self.live_transcriber.get_transcribed_text_queue()
                self.transcript_widget.set_transcript_text_queue(transcribed_text_q)
                self.transcript_widget.clear_text()
                # Initialize with current speaker before first transcript segment arrives
                if hasattr(self.transcript_widget, 'set_current_speaker'):
                    self.transcript_widget.set_current_speaker(self.current_speaker_label)
                self.live_transcriber.start()

                # Setup and start LiveDiarizer
                # Ensure sample_rate is valid (e.g., from AudioRecorder after it's started)
                if self.audio_recorder.samplerate == 0: # Default if not set
                     QMessageBox.critical(self, "Error", "Audio recorder sample rate not set (0). Cannot start diarizer.")
                     self.live_transcriber.stop()
                     self.live_transcriber = None
                     # audio_recorder.stop_recording() needs a filename; how to handle this state?
                     # For now, just prevent diarizer start and update UI.
                     self.vu_meter.set_audio_chunk_queue(None)
                     self.record_button.setEnabled(True) # Allow user to try again
                     self.stop_button.setEnabled(False)
                     self.status_label.setText("Error: Audio sample rate unknown.")
                     return

                self.live_diarizer = LiveDiarizer(
                    audio_input_queue=transcription_audio_q, # Same queue as transcriber
                    sample_rate=self.audio_recorder.samplerate
                )
                self.diarization_result_queue = self.live_diarizer.get_diarization_result_queue()
                self.live_diarizer.start()
                self.diarization_update_timer.start() # Start checking for speaker updates

                self.record_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                self.status_label.setText("Recording, Transcribing & Diarizing...")
                print("Recording, Transcription, and Diarization started.")
            else:
                QMessageBox.critical(self, "Error", "Could not start audio recording.")
                self.status_label.setText("Error: Could not start recording.")
                self.audio_recorder = None
        else:
             QMessageBox.information(self, "Consent Denied", "You have not consented to recording.")
             self.status_label.setText("Consent not given.")

    def _update_current_speaker(self):
        if self.diarization_result_queue:
            latest_speaker = None
            try:
                while not self.diarization_result_queue.empty():
                    # result is (speaker_label, start_time, end_time)
                    speaker_label, _, _ = self.diarization_result_queue.get_nowait()
                    latest_speaker = speaker_label

                if latest_speaker and self.current_speaker_label != latest_speaker:
                    self.current_speaker_label = latest_speaker
                    if hasattr(self.transcript_widget, 'set_current_speaker'):
                        self.transcript_widget.set_current_speaker(self.current_speaker_label)
                    # print(f"Speaker Changed: {self.current_speaker_label}") # Debug
            except queue.Empty:
                pass
            except Exception as e:
                print(f"Error updating speaker data: {e}")

    def _on_stop_button_clicked(self):
        print("Stop button clicked.")
        if self.audio_recorder and self.audio_recorder.is_recording:
            # Stop in reverse order of data flow dependency
            if self.diarization_update_timer.isActive():
                self.diarization_update_timer.stop()
            if self.live_diarizer:
                print("Stopping LiveDiarizer...")
                self.live_diarizer.stop()
                self.live_diarizer = None; self.diarization_result_queue = None
                self.current_speaker_label = "SPEAKER_UKN" # Reset
                if hasattr(self.transcript_widget, 'set_current_speaker'):
                    self.transcript_widget.set_current_speaker(None) # Clear speaker display
                print("LiveDiarizer stopped.")

            if self.live_transcriber:
                print("Stopping LiveTranscriber...")
                self.live_transcriber.stop()
                self.live_transcriber = None
                print("LiveTranscriber stopped.")

            # Now stop the audio source
            self.audio_recorder.stop_recording(output_filename="session_audio.wav")
            self.audio_recorder = None

            self.vu_meter.set_audio_chunk_queue(None)
            self.vu_meter.current_rms_level = 0.0; self.vu_meter.max_rms_level = 0.001; self.vu_meter.update()

            self.record_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Recording stopped. Processes finished. Audio saved.")
            print("All processes stopped and audio saved.")
        else:
            self.status_label.setText("No active recording to stop.")
            # Defensive cleanup if state is inconsistent
            if self.diarization_update_timer.isActive(): self.diarization_update_timer.stop()
            if self.live_diarizer: self.live_diarizer.stop(); self.live_diarizer = None
            if self.live_transcriber: self.live_transcriber.stop(); self.live_transcriber = None
            if self.audio_recorder: self.audio_recorder.stop_recording("error_stop.wav"); self.audio_recorder = None
            self.record_button.setEnabled(True); self.stop_button.setEnabled(False)
            print("Stop clicked but no active recording or inconsistent state.")

    def closeEvent(self, event):
        print("Close event triggered for MainApp.")
        # Ensure all components are stopped
        self._on_stop_button_clicked() # Call the stop logic to ensure graceful shutdown of all parts

        if self.vu_meter and self.vu_meter.timer.isActive():
            self.vu_meter.timer.stop()
        if self.transcript_widget and self.transcript_widget.timer.isActive():
            self.transcript_widget.timer.stop()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainApp()
    main_window.show()
    sys.exit(app.exec_())
