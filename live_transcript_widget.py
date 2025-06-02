import sys
import queue
import random
import time
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QScrollArea, QHBoxLayout, QPushButton
from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette
from PyQt5.QtWidgets import QTextEdit

class LiveTranscriptWidget(QWidget):
    # Signal emitted when transcript is updated
    transcript_updated = pyqtSignal()
    
    def __init__(self, transcript_text_queue=None, parent=None):
        super().__init__(parent)
        self.transcript_text_queue = transcript_text_queue
        self.full_transcript = ""
        self.current_speaker_label = "SPEAKER"
        self.auto_scroll_enabled = True
        self.speaker_colors = {}  # Map speakers to colors
        self.color_palette = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", 
            "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F"
        ]
        self.color_index = 0

        self._init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_transcript)
        self.timer.start(150)

    def _init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        # Control panel
        self.control_layout = QHBoxLayout()
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_text)
        self.control_layout.addWidget(self.clear_button)
        
        self.scroll_toggle_button = QPushButton("Auto-scroll: ON")
        self.scroll_toggle_button.clicked.connect(self._toggle_auto_scroll)
        self.control_layout.addWidget(self.scroll_toggle_button)
        
        self.control_layout.addStretch()
        self.layout.addLayout(self.control_layout)

        # Use QTextEdit instead of QLabel for better formatting
        self.transcript_display = QTextEdit()
        self.transcript_display.setReadOnly(True)
        self.transcript_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.transcript_display.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        font = QFont("Consolas", 11)  # Monospace font for better alignment
        font.setStyleHint(QFont.TypeWriter)
        self.transcript_display.setFont(font)
        
        # Set background color for better readability
        self.transcript_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
            }
        """)

        self.layout.addWidget(self.transcript_display)
        self.setLayout(self.layout)
        self.setMinimumHeight(150)

    def _get_speaker_color(self, speaker):
        """Assign a consistent color to each speaker"""
        if speaker not in self.speaker_colors:
            color = self.color_palette[self.color_index % len(self.color_palette)]
            self.speaker_colors[speaker] = color
            self.color_index += 1
        return self.speaker_colors[speaker]

    def _update_transcript(self):
        if self.transcript_text_queue:
            new_text_added = False
            try:
                while not self.transcript_text_queue.empty():
                    text_segment = self.transcript_text_queue.get_nowait()
                    
                    speaker = self.current_speaker_label if self.current_speaker_label else "Unknown"
                    timestamp = time.strftime("%H:%M:%S")
                    
                    # Get speaker color
                    speaker_color = self._get_speaker_color(speaker)
                    
                    # Format with HTML for colored speaker labels
                    display_segment = f'<span style="color: {speaker_color}; font-weight: bold;">[{speaker}] {timestamp}:</span> {text_segment}'
                    
                    if self.full_transcript:
                        self.full_transcript += "<br>"
                    
                    self.full_transcript += display_segment
                    new_text_added = True
                    
            except queue.Empty:
                pass

            if new_text_added:
                self.transcript_display.setHtml(self.full_transcript)
                
                # Auto-scroll to bottom if enabled
                if self.auto_scroll_enabled:
                    scrollbar = self.transcript_display.verticalScrollBar()
                    scrollbar.setValue(scrollbar.maximum())
                
                # Emit signal for external listeners
                self.transcript_updated.emit()

    def _toggle_auto_scroll(self):
        """Toggle auto-scroll functionality"""
        self.auto_scroll_enabled = not self.auto_scroll_enabled
        status = "ON" if self.auto_scroll_enabled else "OFF"
        self.scroll_toggle_button.setText(f"Auto-scroll: {status}")

    def set_transcript_text_queue(self, text_queue):
        """Set the text queue for transcript updates"""
        self.transcript_text_queue = text_queue

    def set_current_speaker(self, speaker_label):
        """Set the current speaker label"""
        if speaker_label is None:
            self.current_speaker_label = "SPEAKER"
        else:
            self.current_speaker_label = speaker_label

    def clear_text(self):
        """Clear all transcript text"""
        self.full_transcript = ""
        self.current_speaker_label = "SPEAKER"
        self.transcript_display.clear()
        self.speaker_colors.clear()  # Reset speaker colors
        self.color_index = 0

    def export_transcript(self, filename=None):
        """Export transcript to a file"""
        if filename is None:
            filename = f"transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            # Convert HTML to plain text for export
            plain_text = self.transcript_display.toPlainText()
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(plain_text)
            return True
        except Exception as e:
            print(f"Error exporting transcript: {e}")
            return False

    def get_transcript_text(self):
        """Return the current transcript as plain text"""
        return self.transcript_display.toPlainText()

    def get_transcript_html(self):
        """Return the current transcript as HTML"""
        return self.full_transcript

    def set_font_size(self, size):
        """Change the font size of the transcript display"""
        font = self.transcript_display.font()
        font.setPointSize(size)
        self.transcript_display.setFont(font)

    def closeEvent(self, event):
        """Clean up when widget is closed"""
        if hasattr(self, 'timer'):
            self.timer.stop()
        event.accept()


class TranscriptTestWindow(QWidget):
    """Test window with enhanced features"""
    
    def __init__(self):
        super().__init__()
        self.test_text_queue = queue.Queue()
        self.speakers = ["Alice", "Bob", "Charlie", "Diana"]
        self.current_speaker_index = 0
        
        self._init_ui()
        self._setup_test_timer()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # Test controls
        controls_layout = QHBoxLayout()
        
        self.speaker_button = QPushButton("Change Speaker")
        self.speaker_button.clicked.connect(self._change_speaker)
        controls_layout.addWidget(self.speaker_button)
        
        self.export_button = QPushButton("Export Transcript")
        self.export_button.clicked.connect(self._export_transcript)
        controls_layout.addWidget(self.export_button)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Transcript widget
        self.transcript_widget = LiveTranscriptWidget(self.test_text_queue)
        self.transcript_widget.transcript_updated.connect(self._on_transcript_updated)
        layout.addWidget(self.transcript_widget)
        
        self.setWindowTitle("Enhanced Live Transcript Test")
        self.setGeometry(300, 300, 600, 400)

    def _setup_test_timer(self):
        self.test_phrases = [
            "Hello everyone, welcome to the meeting.",
            "Let's start with the quarterly review.",
            "The numbers look good this quarter.",
            "We've seen a 15% increase in revenue.",
            "Customer satisfaction is up as well.",
            "Any questions about the financial report?",
            "Let's move on to the next agenda item.",
            "The new product launch is scheduled for next month.",
            "We need to finalize the marketing strategy.",
            "I think we should focus on digital channels."
        ]
        
        self.test_data_timer = QTimer()
        self.test_data_timer.timeout.connect(self._add_test_text)
        self.test_data_timer.start(2000)  # Add text every 2 seconds

    def _add_test_text(self):
        if random.random() < 0.8:
            phrase = random.choice(self.test_phrases)
            self.test_text_queue.put(phrase)

    def _change_speaker(self):
        self.current_speaker_index = (self.current_speaker_index + 1) % len(self.speakers)
        current_speaker = self.speakers[self.current_speaker_index]
        self.transcript_widget.set_current_speaker(current_speaker)
        self.speaker_button.setText(f"Speaker: {current_speaker}")

    def _export_transcript(self):
        success = self.transcript_widget.export_transcript()
        if success:
            print("Transcript exported successfully!")

    def _on_transcript_updated(self):
        """Handle transcript update signal"""
        # Could update status bar, word count, etc.
        pass


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    window = TranscriptTestWindow()
    window.show()
    
    sys.exit(app.exec_())