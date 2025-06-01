import sys
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QDialogButtonBox, QApplication
)
from PyQt5.QtCore import Qt

class AITrainingConsentDialog(QDialog):
    def __init__(self, speaker_labels: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Training Data Usage Consent")
        self.setModal(True) # Ensure it's modal

        self.speaker_labels = speaker_labels
        self.consent_choices = {}  # To store {speaker_label: checkbox_widget}
        self.collected_consents = None # To store results after 'OK'

        main_layout = QVBoxLayout(self)

        # Top descriptive label
        info_label = QLabel(
            "For each speaker identified in this session, please indicate whether their audio "
            "contributions may be used for AI training purposes. This helps improve our systems."
        )
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)

        # Scroll Area for speaker list
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedHeight(200) # Set a fixed height or make it dynamic

        scroll_content_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_content_widget)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(10)

        if not self.speaker_labels:
            no_speakers_label = QLabel("No distinct speakers were identified in this session.")
            scroll_layout.addWidget(no_speakers_label)
        else:
            for speaker_label in sorted(list(set(self.speaker_labels))): # Ensure unique and sorted
                row_layout = QHBoxLayout()

                speaker_name_label = QLabel(f"<b>{speaker_label}:</b>")
                row_layout.addWidget(speaker_name_label, 1) # Add stretch factor

                checkbox = QCheckBox("Consent to AI Training Use")
                checkbox.setChecked(False) # Default to unchecked (no consent)
                self.consent_choices[speaker_label] = checkbox
                row_layout.addWidget(checkbox)

                scroll_layout.addLayout(row_layout)

        scroll_layout.addStretch(1) # Pushes items to the top if content is short
        scroll_content_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content_widget)
        main_layout.addWidget(scroll_area)

        # Buttons (OK/Cancel)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept) # QDialog's accept slot
        button_box.rejected.connect(self.reject) # QDialog's reject slot
        main_layout.addWidget(button_box)

        self.setLayout(main_layout)
        self.resize(450, 350) # Adjust initial size

    def accept(self):
        """Override to collect data before closing."""
        self.collected_consents = {
            label: checkbox.isChecked() for label, checkbox in self.consent_choices.items()
        }
        super().accept() # Call QDialog.accept()

    def get_collected_consents(self) -> dict or None:
        """
        Returns the consent choices made by the user if the dialog was accepted.
        Returns None if the dialog was cancelled or not yet accepted.
        """
        return self.collected_consents


if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Test cases
    test_speakers_1 = ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_00"] # Includes duplicate
    test_speakers_2 = [] # No speakers
    test_speakers_3 = [f"SPEAKER_{i:02d}" for i in range(10)] # More speakers to test scroll

    print("--- Test Case 1: Regular Speakers ---")
    dialog1 = AITrainingConsentDialog(speaker_labels=test_speakers_1)
    if dialog1.exec_() == QDialog.Accepted:
        consents = dialog1.get_collected_consents()
        print("Consents Given (Test 1):", consents)
    else:
        print("Dialog 1 Cancelled.")

    print("\n--- Test Case 2: No Speakers ---")
    dialog2 = AITrainingConsentDialog(speaker_labels=test_speakers_2)
    if dialog2.exec_() == QDialog.Accepted: # Should still show dialog, just with "no speakers" message
        consents = dialog2.get_collected_consents()
        print("Consents Given (Test 2):", consents) # Will be empty dict
    else:
        print("Dialog 2 Cancelled.")

    print("\n--- Test Case 3: Many Speakers (Test Scroll) ---")
    dialog3 = AITrainingConsentDialog(speaker_labels=test_speakers_3)
    if dialog3.exec_() == QDialog.Accepted:
        consents = dialog3.get_collected_consents()
        print("Consents Given (Test 3):", consents)
    else:
        print("Dialog 3 Cancelled.")

    # No sys.exit(app.exec_()) needed here as QDialog.exec_() runs its own event loop.
    # The script will exit after the last dialog is closed or cancelled.
    # If there were non-modal windows, app.exec_() would be needed at the end.
    sys.exit(0) # Explicitly exit for sandbox environment if needed.
