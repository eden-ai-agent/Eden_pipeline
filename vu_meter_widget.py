import sys
import queue
import random
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPainter, QColor, QBrush
from PyQt5.QtCore import QTimer, QRectF, Qt

class VUMeterWidget(QWidget):
    def __init__(self, audio_chunk_queue=None, parent=None):
        super().__init__(parent)
        self.audio_chunk_queue = audio_chunk_queue
        self.current_rms_level = 0.0
        self.max_rms_level = 0.001 # To avoid division by zero, and represent silence

        self.setMinimumSize(150, 30) # Width, Height
        self.setMaximumHeight(50)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_level)
        self.timer.start(50)  # Update interval in milliseconds (e.g., 50ms for 20 FPS)

    def set_audio_chunk_queue(self, audio_queue):
        self.audio_chunk_queue = audio_queue
        self.current_rms_level = 0.0 # Reset level when queue changes
        self.max_rms_level = 0.001   # Reset max level

    def _update_level(self):
        if self.audio_chunk_queue:
            try:
                # Process all available items in the queue since last update
                # to ensure responsiveness, but only use the latest for display.
                # Or average them, or take max. For a VU meter, max is often good.
                level_sum = 0
                items_count = 0
                max_in_batch = 0

                while not self.audio_chunk_queue.empty():
                    rms = self.audio_chunk_queue.get_nowait()
                    if rms > max_in_batch:
                        max_in_batch = rms
                    items_count +=1

                if items_count > 0:
                    self.current_rms_level = max_in_batch
                    if self.current_rms_level > self.max_rms_level:
                        self.max_rms_level = self.current_rms_level
                # else:
                    # If queue was empty, slowly decay the current level
                    # self.current_rms_level *= 0.8
                    # For simplicity, we'll just hold the last value or let it be 0 if no new data.
                    # If no new data, we can let it decay here.
                    # self.current_rms_level = self.current_rms_level * 0.8 # Decay effect

                self.update()  # Schedule a repaint
            except queue.Empty:
                # If queue is empty, decay the current level slowly
                # self.current_rms_level *= 0.8
                # self.update()
                pass # No new data, do nothing or implement decay
            except Exception as e:
                print(f"Error reading from VU meter queue: {e}")
        else:
            # If no queue, maybe show a disabled state or just zero
            if self.current_rms_level > 0: # Decay if it was showing something
                self.current_rms_level *= 0.8
                if self.current_rms_level < 0.01:
                    self.current_rms_level = 0.0
                self.update()


    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect() # The widget's bounding rectangle
        # painter.fillRect(rect, Qt.black) # Background

        # Normalize RMS level: RMS values can be small (e.g., 0.0 to 0.5).
        # We need a reference max for full scale, or let it adapt.
        # For simplicity, let's assume RMS values are typically within 0-0.5 for speech,
        # and can peak up to 1.0 or slightly more for loud sounds.
        # We can use a dynamic max_rms_level or a fixed one.
        # Let's try to make it relative to a typical "loud" signal, say 0.7

        # Effective RMS for display (clamped and normalized)
        # Clamp value for safety, e.g. max 1.5 times the observed max, or a fixed sensible max
        display_rms = min(self.current_rms_level, self.max_rms_level * 1.5 if self.max_rms_level > 0.1 else 0.1)

        # Normalize based on a somewhat adaptive maximum, or a fixed one like 0.5
        # Reference max could be something like 0.5 for "loud enough"
        reference_max = 0.5
        normalized_level = min(display_rms / reference_max, 1.2) # Allow some overshooting display

        bar_width_ratio = normalized_level

        meter_rect_width = rect.width() * bar_width_ratio
        meter_rect_height = rect.height() - 10 # Leave some padding

        meter_rect = QRectF(5, 5, meter_rect_width, meter_rect_height)

        # Color based on level
        if normalized_level > 0.95: # Clipping (or very loud)
            color = QColor(Qt.red)
        elif normalized_level > 0.7: # Loud
            color = QColor(Qt.yellow)
        else: # Normal
            color = QColor(Qt.green)

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen) # No border for the bar itself
        painter.drawRect(meter_rect)

        # Draw a border for the whole widget area
        painter.setPen(QColor(Qt.gray))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(0,0,-1,-1)) # adjust to draw inside bounds

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Create a dummy queue for testing
    test_queue = queue.Queue()

    vu_meter = VUMeterWidget(test_queue)
    vu_meter.setWindowTitle("VU Meter Test")
    vu_meter.setGeometry(200, 200, 200, 50)
    vu_meter.show()

    # Simulate RMS data being added to the queue
    def add_test_data():
        # Simulate varying RMS levels
        if random.random() < 0.7: # 70% chance of new data
            level = random.uniform(0.0, 0.8) # Normal levels
            if random.random() < 0.1: # 10% chance of a peak
                level = random.uniform(0.7, 1.2)
            test_queue.put(level)
            # print(f"Test RMS: {level:.3f}, Queue size: {test_queue.qsize()}")

    test_data_timer = QTimer()
    test_data_timer.timeout.connect(add_test_data)
    test_data_timer.start(70) # Add data slightly more frequently than VU meter updates

    sys.exit(app.exec_())
