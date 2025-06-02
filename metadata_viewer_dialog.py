import sys
import json
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QTextEdit,
    QFileDialog, QMessageBox, QApplication, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont # For setting monospaced font

class MetadataViewerDialog(QDialog):
    def __init__(self, parent=None, initial_dir="sessions_output"):
        super().__init__(parent)
        self.setWindowTitle("View Session Metadata")
        self.initial_dir = initial_dir
        if not os.path.exists(self.initial_dir):
            # If the default sessions_output doesn't exist, fallback to current dir
            self.initial_dir = "."


        main_layout = QVBoxLayout(self)

        # Text Edit for JSON Display
        self.json_display = QTextEdit()
        self.json_display.setReadOnly(True)
        self.json_display.setLineWrapMode(QTextEdit.NoWrap) # Horizontal scroll for long lines

        # Set a monospaced font like Courier New or Consolas
        font = QFont("Courier New", 10) # Courier New is widely available
        if not font.exactMatch(): # Fallback if Courier New isn't found
            font.setFamily("Monospace") # Generic fallback
            font.setPointSize(10)
        self.json_display.setFont(font)

        main_layout.addWidget(self.json_display, 1) # Add stretch factor for text edit

        # Buttons
        button_layout = QHBoxLayout() # Layout for buttons

        self.load_button = QPushButton("Load metadata.json File")
        self.load_button.clicked.connect(self.load_metadata_file)
        button_layout.addWidget(self.load_button)
        button_layout.addStretch(1) # Push load button to left, close to right

        self.close_button_box = QDialogButtonBox(QDialogButtonBox.Close)
        self.close_button_box.rejected.connect(self.reject) # Close on "Close"
        button_layout.addWidget(self.close_button_box)

        main_layout.addLayout(button_layout) # Add button layout to main layout

        self.setLayout(main_layout)
        self.resize(700, 800)

    def load_metadata_file(self):
        options = QFileDialog.Options()
        # options |= QFileDialog.DontUseNativeDialog # Uncomment for non-native dialog if needed
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open metadata.json File",
            self.initial_dir,
            "JSON Files (*.json);;All Files (*)",
            options=options
        )

        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    metadata_dict = json.load(f)
                pretty_json = json.dumps(metadata_dict, indent=4, sort_keys=True)
                self.json_display.setText(pretty_json)
                self.setWindowTitle(f"View Session Metadata - {os.path.basename(filepath)}")
                # Update initial_dir to the directory of the loaded file for next time
                self.initial_dir = os.path.dirname(filepath)
            except Exception as e:
                error_message = f"Error loading or parsing JSON file: {filepath}\n\n{str(e)}"
                self.json_display.setText(error_message)
                QMessageBox.critical(self, "Load Error", f"Could not load or parse file: {e}")
                self.setWindowTitle("View Session Metadata - Error")


if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Create a dummy metadata.json for testing
    dummy_dir_path = os.path.join("sessions_output", "test_session_for_viewer", "standard")
    os.makedirs(dummy_dir_path, exist_ok=True)
    dummy_metadata_file = os.path.join(dummy_dir_path, "metadata.json")

    sample_metadata_content = {
        "session_id": "DUMMY_SESSION_123",
        "session_start_time": datetime.now().isoformat(),
        "description": "This is a test metadata file for the MetadataViewerDialog.",
        "data_points": [1, 2, 3],
        "nested_info": {"keyA": "valueA", "keyB": [4,5,6]}
    }
    try:
        with open(dummy_metadata_file, 'w', encoding='utf-8') as f:
            json.dump(sample_metadata_content, f, indent=4)
        print(f"Dummy metadata file created at: {dummy_metadata_file}")
    except Exception as e:
        print(f"Could not create dummy metadata file: {e}")

    # Pass the directory containing the dummy session, not the "standard" subdirectory directly for initial_dir
    dialog = MetadataViewerDialog(initial_dir=os.path.dirname(dummy_dir_path)) # "sessions_output/test_session_for_viewer"

    # To load the dummy file automatically for testing:
    # dialog.load_metadata_file() # This would open file dialog, not ideal for auto-test
    # Instead, we can set the text directly for a quick UI check IF no file dialog is desired in test.
    # Or just show the dialog and let user click "Load".

    dialog.show()

    # If you want to test loading a specific file without manual interaction:
    # dialog.json_display.setText(json.dumps(sample_metadata_content, indent=4, sort_keys=True))
    # dialog.setWindowTitle(f"View Session Metadata - {os.path.basename(dummy_metadata_file)}")


    exit_code = app.exec_()

    # Clean up dummy file and directory
    # try:
    #     if os.path.exists(dummy_metadata_file):
    #         os.remove(dummy_metadata_file)
    #     if os.path.exists(dummy_dir_path): # Remove "standard"
    #         os.rmdir(dummy_dir_path)
    #     if os.path.exists(os.path.dirname(dummy_dir_path)): # Remove "test_session_for_viewer"
    #         os.rmdir(os.path.dirname(dummy_dir_path))
    #     # Could also remove "sessions_output" if it was created solely for this test and is empty
    # except OSError as e:
    #     print(f"Error during cleanup: {e}")
    print(f"Test metadata file '{dummy_metadata_file}' is available for inspection if needed.")


    sys.exit(exit_code)
