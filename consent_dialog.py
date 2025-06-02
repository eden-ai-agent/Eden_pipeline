import sys
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QPushButton, 
    QHBoxLayout, QTextEdit, QScrollArea, QCheckBox, QFrame,
    QMessageBox, QGroupBox, QGridLayout, QSpacerItem, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPalette

class ConsentDialog(QDialog):
    """
    Enhanced consent dialog for audio recording with comprehensive legal compliance.
    
    Features:
    - Detailed consent information
    - Scrollable terms and conditions
    - Consent persistence and validation
    - Customizable consent duration
    - Legal compliance helpers
    - Audit trail generation
    """
    
    # Signal emitted when consent status changes
    consent_changed = pyqtSignal(bool, str)
    
    def __init__(self, 
                 parent=None, 
                 consent_duration_days: int = 365,
                 app_name: str = "Audio Recording Application",
                 organization: str = "Your Organization",
                 purpose: str = "voice analysis and transcription",
                 data_retention_days: int = 90,
                 consent_file: str = "consent_records.json"):
        """
        Initialize the consent dialog.
        
        Args:
            parent: Parent widget
            consent_duration_days: How long consent is valid (default: 1 year)
            app_name: Name of the application
            organization: Organization name
            purpose: Purpose of recording
            data_retention_days: How long data is retained
            consent_file: File to store consent records
        """
        super().__init__(parent)
        
        # Configuration
        self.consent_duration_days = consent_duration_days
        self.app_name = app_name
        self.organization = organization
        self.purpose = purpose
        self.data_retention_days = data_retention_days
        self.consent_file = consent_file
        
        # State
        self.consent_given = False
        self.consent_timestamp = None
        self.user_id = None
        self.session_id = None
        
        # UI Setup
        self._setup_dialog()
        self._create_ui()
        self._load_existing_consent()
        
        # Auto-close timer (optional safety feature)
        self.auto_close_timer = QTimer()
        self.auto_close_timer.timeout.connect(self._auto_close)
        
    def _setup_dialog(self):
        """Configure dialog properties."""
        self.setWindowTitle(f"{self.app_name} - Recording Consent")
        self.setMinimumSize(500, 600)
        self.setMaximumSize(700, 800)
        self.resize(600, 700)
        
        # Make dialog modal and prevent closing with X button without explicit choice
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        
    def _create_ui(self):
        """Create the user interface."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # Header
        header_label = QLabel(f"Audio Recording Consent - {self.app_name}")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header_label)
        
        # Consent information group
        consent_group = QGroupBox("Consent Information")
        consent_layout = QVBoxLayout(consent_group)
        
        # Main consent message
        consent_text = self._generate_consent_text()
        consent_label = QLabel(consent_text)
        consent_label.setWordWrap(True)
        consent_label.setStyleSheet("QLabel { padding: 10px; background-color: #f0f0f0; border-radius: 5px; }")
        consent_layout.addWidget(consent_label)
        
        main_layout.addWidget(consent_group)
        
        # Detailed terms (scrollable)
        terms_group = QGroupBox("Terms and Conditions")
        terms_layout = QVBoxLayout(terms_group)
        
        terms_scroll = QScrollArea()
        terms_scroll.setMaximumHeight(200)
        terms_scroll.setWidgetResizable(True)
        
        terms_text = QTextEdit()
        terms_text.setPlainText(self._generate_detailed_terms())
        terms_text.setReadOnly(True)
        terms_scroll.setWidget(terms_text)
        
        terms_layout.addWidget(terms_scroll)
        main_layout.addWidget(terms_group)
        
        # Consent checkboxes
        checkboxes_group = QGroupBox("Required Confirmations")
        checkboxes_layout = QVBoxLayout(checkboxes_group)
        
        self.understand_checkbox = QCheckBox(
            "I understand that my voice will be recorded and processed"
        )
        self.agree_terms_checkbox = QCheckBox(
            "I have read and agree to the terms and conditions above"
        )
        self.data_processing_checkbox = QCheckBox(
            f"I consent to my data being retained for up to {self.data_retention_days} days"
        )
        
        for checkbox in [self.understand_checkbox, self.agree_terms_checkbox, self.data_processing_checkbox]:
            checkbox.stateChanged.connect(self._validate_checkboxes)
            checkboxes_layout.addWidget(checkbox)
        
        main_layout.addWidget(checkboxes_group)
        
        # Consent validity information
        validity_label = QLabel(
            f"This consent will be valid for {self.consent_duration_days} days from today."
        )
        validity_label.setStyleSheet("QLabel { font-style: italic; color: #666; }")
        main_layout.addWidget(validity_label)
        
        # Spacer
        spacer = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)
        main_layout.addItem(spacer)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.consent_button = QPushButton("✓ Yes, I Give Consent")
        self.consent_button.setEnabled(False)  # Disabled until checkboxes are checked
        self.consent_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.consent_button.clicked.connect(self._handle_consent)
        
        self.cancel_button = QPushButton("✗ No, I Do Not Consent")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.cancel_button.clicked.connect(self._handle_cancel)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.consent_button)
        
        main_layout.addLayout(button_layout)
        
    def _generate_consent_text(self) -> str:
        """Generate the main consent text."""
        return f"""
IMPORTANT: Recording Consent Required

{self.organization} requests your consent to record audio during your use of {self.app_name}.

PURPOSE: The recording will be used for {self.purpose}.

WHAT IS RECORDED: Your voice and any audio captured by your microphone during the session.

DATA HANDLING: Recorded data will be processed securely and retained for up to {self.data_retention_days} days, after which it will be permanently deleted.

YOUR RIGHTS: You may withdraw consent at any time by closing the application. You have the right to request deletion of your recorded data.

CONSENT VALIDITY: This consent is valid for {self.consent_duration_days} days from the date given.
        """.strip()
        
    def _generate_detailed_terms(self) -> str:
        """Generate detailed terms and conditions."""
        return f"""
DETAILED TERMS AND CONDITIONS

1. DATA COLLECTION
   - Audio recordings will be captured from your microphone
   - Recordings may include background noise and other participants if present
   - Session metadata (timestamps, duration) will be collected

2. DATA PROCESSING
   - Audio may be transcribed to text using automated systems
   - Voice analysis may be performed for the stated purpose
   - Data processing may involve third-party services with appropriate safeguards

3. DATA STORAGE AND SECURITY
   - All recordings are encrypted during transmission and storage
   - Data is stored on secure servers with restricted access
   - Regular security audits are performed

4. DATA RETENTION
   - Recordings will be retained for up to {self.data_retention_days} days
   - After retention period, data will be permanently and securely deleted
   - You may request earlier deletion by contacting {self.organization}

5. YOUR RIGHTS
   - Right to withdraw consent at any time
   - Right to request access to your recorded data
   - Right to request correction or deletion of your data
   - Right to file complaints with relevant authorities

6. CONTACT INFORMATION
   - Organization: {self.organization}
   - For data protection queries, contact your system administrator

7. LEGAL BASIS
   - Processing is based on your explicit consent
   - Consent can be withdrawn without affecting previous processing
   - Some processing may be necessary for legitimate interests

8. INTERNATIONAL TRANSFERS
   - Data may be transferred internationally with appropriate safeguards
   - Adequate protection measures are in place for all transfers

By providing consent, you acknowledge that you have read, understood, and agree to these terms.

Last updated: {datetime.now().strftime('%Y-%m-%d')}
        """.strip()
        
    def _validate_checkboxes(self):
        """Enable/disable consent button based on checkbox states."""
        all_checked = (
            self.understand_checkbox.isChecked() and
            self.agree_terms_checkbox.isChecked() and
            self.data_processing_checkbox.isChecked()
        )
        self.consent_button.setEnabled(all_checked)
        
    def _handle_consent(self):
        """Handle consent given by user."""
        if not self._validate_consent():
            return
            
        self.consent_given = True
        self.consent_timestamp = datetime.now()
        
        # Save consent record
        self._save_consent_record()
        
        # Emit signal
        self.consent_changed.emit(True, "Consent granted")
        
        # Show confirmation
        QMessageBox.information(
            self,
            "Consent Recorded",
            f"Thank you. Your consent has been recorded and is valid until "
            f"{(self.consent_timestamp + timedelta(days=self.consent_duration_days)).strftime('%Y-%m-%d')}."
        )
        
        self.accept()
        
    def _handle_cancel(self):
        """Handle consent denied by user."""
        self.consent_given = False
        self.consent_timestamp = None
        
        # Show information about implications
        reply = QMessageBox.question(
            self,
            "Consent Required",
            "Audio recording consent is required to use this application. "
            "Without consent, the application cannot function.\n\n"
            "Are you sure you want to proceed without giving consent?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.consent_changed.emit(False, "Consent denied")
            self.reject()
        # If No, stay in dialog
        
    def _validate_consent(self) -> bool:
        """Validate that consent can be given."""
        if not all([
            self.understand_checkbox.isChecked(),
            self.agree_terms_checkbox.isChecked(),
            self.data_processing_checkbox.isChecked()
        ]):
            QMessageBox.warning(
                self,
                "Incomplete Consent",
                "Please check all required boxes before giving consent."
            )
            return False
        return True
        
    def _save_consent_record(self):
        """Save consent record to file for audit purposes."""
        try:
            # Load existing records
            consent_records = []
            if os.path.exists(self.consent_file):
                with open(self.consent_file, 'r') as f:
                    consent_records = json.load(f)
            
            # Add new record
            record = {
                "timestamp": self.consent_timestamp.isoformat(),
                "user_id": self.user_id or "anonymous",
                "session_id": self.session_id or f"session_{int(datetime.now().timestamp())}",
                "consent_given": self.consent_given,
                "app_name": self.app_name,
                "organization": self.organization,
                "purpose": self.purpose,
                "consent_duration_days": self.consent_duration_days,
                "data_retention_days": self.data_retention_days,
                "valid_until": (self.consent_timestamp + timedelta(days=self.consent_duration_days)).isoformat(),
                "ip_address": "127.0.0.1",  # In real app, get actual IP
                "user_agent": f"{self.app_name} Desktop Client"
            }
            
            consent_records.append(record)
            
            # Save records
            with open(self.consent_file, 'w') as f:
                json.dump(consent_records, f, indent=2, default=str)
                
        except Exception as e:
            print(f"Warning: Could not save consent record: {e}")
            
    def _load_existing_consent(self):
        """Check if valid consent already exists."""
        try:
            if not os.path.exists(self.consent_file):
                return
                
            with open(self.consent_file, 'r') as f:
                records = json.load(f)
            
            # Find most recent valid consent for this user/session
            current_time = datetime.now()
            
            for record in reversed(records):  # Check most recent first
                if (record.get('user_id') == (self.user_id or "anonymous") and
                    record.get('consent_given', False)):
                    
                    valid_until = datetime.fromisoformat(record['valid_until'])
                    if current_time < valid_until:
                        # Valid consent exists
                        self.consent_given = True
                        self.consent_timestamp = datetime.fromisoformat(record['timestamp'])
                        
                        # Ask if user wants to use existing consent
                        reply = QMessageBox.question(
                            self,
                            "Existing Consent Found",
                            f"You have already given consent on {self.consent_timestamp.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                            f"This consent is valid until {valid_until.strftime('%Y-%m-%d')}.\n\n"
                            "Would you like to use your existing consent?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.Yes
                        )
                        
                        if reply == QMessageBox.Yes:
                            self.accept()
                            return
                        else:
                            # Reset for new consent
                            self.consent_given = False
                            self.consent_timestamp = None
                        break
                        
        except Exception as e:
            print(f"Warning: Could not load existing consent: {e}")
            
    def _auto_close(self):
        """Auto-close dialog after timeout (safety feature)."""
        QMessageBox.warning(
            self,
            "Session Timeout",
            "Dialog timed out. Please restart the application if you wish to give consent."
        )
        self.reject()
        
    def set_user_info(self, user_id: str, session_id: str):
        """Set user identification for consent tracking."""
        self.user_id = user_id
        self.session_id = session_id
        
    def set_auto_close_timeout(self, seconds: int):
        """Set auto-close timeout in seconds (0 to disable)."""
        if seconds > 0:
            self.auto_close_timer.start(seconds * 1000)
        else:
            self.auto_close_timer.stop()
            
    def get_consent_status(self) -> bool:
        """Get consent status."""
        return self.consent_given
        
    def get_consent_timestamp(self) -> Optional[datetime]:
        """Get consent timestamp."""
        return self.consent_timestamp if self.consent_given else None
        
    def get_consent_expiry(self) -> Optional[datetime]:
        """Get consent expiry date."""
        if self.consent_given and self.consent_timestamp:
            return self.consent_timestamp + timedelta(days=self.consent_duration_days)
        return None
        
    def is_consent_valid(self) -> bool:
        """Check if current consent is still valid."""
        if not self.consent_given or not self.consent_timestamp:
            return False
        return datetime.now() < self.get_consent_expiry()

# Utility function for easy integration
def get_user_consent(parent=None, **kwargs) -> tuple[bool, Optional[datetime]]:
    """
    Utility function to easily get user consent.
    
    Returns:
        Tuple of (consent_given, consent_timestamp)
    """
    dialog = ConsentDialog(parent, **kwargs)
    result = dialog.exec_()
    
    return dialog.get_consent_status(), dialog.get_consent_timestamp()

# Demo and testing
def run_comprehensive_demo():
    """Run comprehensive demo of the consent dialog."""
    app = QApplication(sys.argv)
    
    print("=== Enhanced Consent Dialog Demo ===\n")
    
    # Test Case 1: Basic consent flow
    print("--- Test Case 1: Basic Consent Flow ---")
    dialog1 = ConsentDialog(
        app_name="Voice Analysis Pro",
        organization="AI Research Lab",
        purpose="speech pattern analysis and machine learning research",
        consent_duration_days=180,
        data_retention_days=30
    )
    
    # Set user info for tracking
    dialog1.set_user_info("user123", "session_001")
    
    # Optional: Set auto-close timeout (for demo, use longer timeout)
    # dialog1.set_auto_close_timeout(300)  # 5 minutes
    
    result1 = dialog1.exec_()
    
    print(f"Dialog result: {'Accepted' if result1 == QDialog.Accepted else 'Rejected'}")
    print(f"Consent given: {dialog1.get_consent_status()}")
    print(f"Consent timestamp: {dialog1.get_consent_timestamp()}")
    print(f"Consent valid: {dialog1.is_consent_valid()}")
    if dialog1.get_consent_expiry():
        print(f"Consent expires: {dialog1.get_consent_expiry().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Test Case 2: Using utility function
    print("--- Test Case 2: Utility Function ---")
    consent_given, consent_time = get_user_consent(
        app_name="Simple Recorder",
        purpose="meeting transcription"
    )
    
    print(f"Utility function result: Consent={consent_given}, Time={consent_time}")
    print()
    
    # Test Case 3: Existing consent check
    print("--- Test Case 3: Existing Consent Check ---")
    dialog3 = ConsentDialog(
        app_name="Voice Analysis Pro",
        organization="AI Research Lab",
        consent_file="consent_records.json"
    )
    dialog3.set_user_info("user123", "session_002")  # Same user
    
    # This should find existing consent if previous test was accepted
    result3 = dialog3.exec_()
    
    print(f"Second dialog result: {'Accepted' if result3 == QDialog.Accepted else 'Rejected'}")
    print(f"Used existing consent: {dialog3.get_consent_status()}")
    
    print("\n--- Demo Complete ---")
    print("Check 'consent_records.json' for audit trail.")

if __name__ == '__main__':
    try:
        run_comprehensive_demo()
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"Demo error: {e}")
        raise