import sys
import queue
import random
import time # For test block
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QScrollArea
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

class LiveTranscriptWidget(QWidget):
    def __init__(self, transcript_text_queue=None, parent=None):
        super().__init__(parent)
        self.transcript_text_queue = transcript_text_queue
        self.full_transcript = ""
        self.current_speaker_label = "SPEAKER" # Default speaker label

        self._init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_transcript)
        self.timer.start(150)  # Update interval in milliseconds

    def _init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0) # Use full space

        self.transcript_label = QLabel(self.full_transcript)
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setAlignment(Qt.AlignTop)

        font = QFont()
        font.setPointSize(12) # Slightly larger font
        self.transcript_label.setFont(font)
        # self.transcript_label.setStyleSheet("padding: 5px;")


        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.transcript_label)
        # self.scroll_area.setStyleSheet("border: 1px solid #ccc;")


        self.layout.addWidget(self.scroll_area)
        self.setLayout(self.layout)
        self.setMinimumHeight(100)


    def _update_transcript(self):
        if self.transcript_text_queue:
            updated = False
            try:
                new_text_added = False
                while not self.transcript_text_queue.empty():
                    text_segment = self.transcript_text_queue.get_nowait()

                    # Prepare display segment with speaker label
                    speaker = self.current_speaker_label if self.current_speaker_label else "Unknown"
                    display_segment = f"[{speaker}]: {text_segment}"

                    if self.full_transcript: # If there's existing text
                        if not self.full_transcript.endswith("\n"):
                            self.full_transcript += "\n" # Ensure new segment starts on a new line

                    self.full_transcript += display_segment
                    new_text_added = True
            except queue.Empty:
                pass # No new text

            if new_text_added:
                self.transcript_label.setText(self.full_transcript)
                # Scroll to bottom only if new text was actually added
                self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().maximum()
                )
        # If no queue, do nothing. Label will retain old text or be empty.

    def set_transcript_text_queue(self, text_queue):
        self.transcript_text_queue = text_queue
        # self.clear_text() # Optionally clear text when new queue is set

    def set_current_speaker(self, speaker_label):
        if speaker_label is None:
            self.current_speaker_label = "SPEAKER" # Default if None
        else:
            self.current_speaker_label = speaker_label
        # print(f"TranscriptWidget: Speaker set to {self.current_speaker_label}") # For debugging

    def clear_text(self):
        self.full_transcript = ""
        self.current_speaker_label = "SPEAKER" # Reset to default
        self.transcript_label.setText(self.full_transcript)
        self.scroll_area.verticalScrollBar().setValue(0)

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Create a dummy queue for testing
    test_text_queue = queue.Queue()

    transcript_widget = LiveTranscriptWidget(test_text_queue)
    transcript_widget.setWindowTitle("Live Transcript Test")
    transcript_widget.setGeometry(300, 300, 400, 200)
    transcript_widget.show()

    # Simulate new transcript segments being added to the queue
    test_phrases = [
        "Hello world.", "This is a test.", "The quick brown fox jumps over the lazy dog.",
        "Live transcription in progress.", "Segment one.", "Another piece of text.",
        "What will happen next?", "This is a longer sentence to check word wrapping and scrolling functionality effectively."
    ]

    def add_test_text():
        if random.random() < 0.8: # Chance to add text
            phrase = random.choice(test_phrases)
            test_text_queue.put(phrase)
            # print(f"Added to queue: '{phrase}'")

    test_data_timer = QTimer()
    test_data_timer.timeout.connect(add_test_text)
    test_data_timer.start(1000) # Add a new phrase every second

    sys.exit(app.exec_())
