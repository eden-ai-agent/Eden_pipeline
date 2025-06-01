import sys
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from datetime import datetime

class ConsentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recording Consent")
        self.consent_given = False
        self.consent_timestamp = None

        layout = QVBoxLayout(self)

        message_label = QLabel(
            "This application records audio. By clicking 'Yes, I Consent', "
            "you agree to the recording of this session. This consent is "
            "valid for 1 year from the date of this session."
        )
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        button_layout = QHBoxLayout()

        self.consent_button = QPushButton("Yes, I Consent")
        self.consent_button.clicked.connect(self._handle_consent)
        button_layout.addWidget(self.consent_button)

        self.cancel_button = QPushButton("No, Cancel")
        self.cancel_button.clicked.connect(self._handle_cancel)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

    def _handle_consent(self):
        self.consent_given = True
        self.consent_timestamp = datetime.now()
        self.accept() # QDialog.accept() closes the dialog and sets result to Accepted

    def _handle_cancel(self):
        self.consent_given = False
        # self.consent_timestamp remains None or its previous value if dialog was shown multiple times
        self.reject() # QDialog.reject() closes the dialog and sets result to Rejected

    def get_consent_status(self):
        return self.consent_given

    def get_consent_timestamp(self):
        return self.consent_timestamp if self.consent_given else None

if __name__ == '__main__':
    app = QApplication(sys.argv)

    print("--- Test Case 1: User Consents ---")
    dialog_consent = ConsentDialog()
    result_consent = dialog_consent.exec_() # This will block until the dialog is closed

    print("Dialog closed.")
    print("Consent Given:", dialog_consent.get_consent_status())
    print("Consent Timestamp:", dialog_consent.get_consent_timestamp())
    if result_consent == QDialog.Accepted:
        print("Dialog result: Accepted")
    else:
        print("Dialog result: Rejected")
    print("-" * 30)

    print("\n--- Test Case 2: User Cancels ---")
    dialog_cancel = ConsentDialog()
    result_cancel = dialog_cancel.exec_() # This will block until the dialog is closed

    print("Dialog closed.")
    print("Consent Given:", dialog_cancel.get_consent_status())
    print("Consent Timestamp:", dialog_cancel.get_consent_timestamp())
    if result_cancel == QDialog.Accepted:
        print("Dialog result: Accepted")
    else:
        print("Dialog result: Rejected (or closed via window [X])")
    print("-" * 30)

    # Note: QApplication.exec_() is called by QDialog.exec_(),
    # so we don't need a final app.exec_() here if we only run dialogs.
    # If there were other Qt windows, we would need it.
    # sys.exit() # Exiting here would prevent the second dialog test if not careful
    # For simplicity, let the script end. If app.exec_() is needed for other reasons,
    # it should be the last Qt call.
