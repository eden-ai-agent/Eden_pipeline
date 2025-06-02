import sys
import json
from datetime import datetime, timezone, timedelta
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QScrollArea, QWidget,
    QFormLayout, QDialogButtonBox, QTextEdit, QApplication, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QProgressBar, QFrame, QSplitter, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPalette, QColor

class SessionSummaryDialog(QDialog):
    export_requested = pyqtSignal(str)  # Signal for export requests
    
    def __init__(self, metadata_dict: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Summary & Metadata")
        self.metadata = metadata_dict
        self.setModal(True)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        # Header with session info
        self._create_header(main_layout)
        
        # Tabbed interface for better organization
        self.tab_widget = QTabWidget()
        self._create_summary_tab()
        self._create_security_tab()
        self._create_speakers_tab()
        self._create_files_tab()
        self._create_raw_metadata_tab()
        
        main_layout.addWidget(self.tab_widget)
        
        # Footer with buttons
        self._create_footer(main_layout)
        
        self.setLayout(main_layout)
        self.resize(700, 600)
        
        # Apply styling
        self._apply_styling()

    def _create_header(self, layout):
        """Create header section with key session info"""
        header_frame = QFrame()
        header_frame.setFrameStyle(QFrame.StyledPanel)
        header_layout = QVBoxLayout(header_frame)
        
        # Session title
        session_id = self.metadata.get('session_id', 'Unknown Session')
        title_label = QLabel(f"<h2>{session_id}</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(title_label)
        
        # Quick stats in horizontal layout
        stats_layout = QHBoxLayout()
        
        # Duration
        duration_str = self._calculate_duration()
        duration_label = QLabel(f"<b>Duration:</b> {duration_str}")
        stats_layout.addWidget(duration_label)
        
        # Speakers count
        speakers_count = len(self.metadata.get('diarization_summary', {}).get('speakers_identified', []))
        speakers_label = QLabel(f"<b>Speakers:</b> {speakers_count}")
        stats_layout.addWidget(speakers_label)
        
        # Encryption status
        enc_status = "🔒 Encrypted" if self._is_encrypted() else "🔓 Unencrypted"
        enc_label = QLabel(f"<b>Security:</b> {enc_status}")
        stats_layout.addWidget(enc_label)
        
        header_layout.addLayout(stats_layout)
        layout.addWidget(header_frame)

    def _create_summary_tab(self):
        """Create the main summary tab"""
        summary_widget = QWidget()
        layout = QVBoxLayout(summary_widget)
        
        # Create scrollable form
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)
        
        # Session details
        form_layout.addRow("Session ID:", QLabel(str(self.metadata.get('session_id', 'N/A'))))
        form_layout.addRow("Duration:", QLabel(self._calculate_duration()))
        
        # Timestamps
        start_time = self._format_timestamp(self.metadata.get('session_start_time'))
        end_time = self._format_timestamp(self.metadata.get('session_end_time'))
        form_layout.addRow("Start Time:", QLabel(start_time))
        form_layout.addRow("End Time:", QLabel(end_time))
        
        # Consent information
        consent_info = self._get_consent_info()
        form_layout.addRow("Recording Consent:", QLabel(consent_info))
        
        # AI Training consents
        ai_consent_info = self._get_ai_consent_info()
        form_layout.addRow("AI Training Consents:", QLabel(ai_consent_info))
        
        # PHI/PII Detection
        phi_count = len(self.metadata.get('phi_pii_detected_in_transcript', []))
        mute_count = len(self.metadata.get('phi_pii_audio_mute_segments', []))
        form_layout.addRow("PHI/PII Detected:", QLabel(f"{phi_count} instances"))
        form_layout.addRow("Audio Segments Muted:", QLabel(f"{mute_count} segments"))
        
        # Emotions
        emotions_info = self._get_emotions_info()
        form_layout.addRow("Dominant Emotions:", QLabel(emotions_info))
        
        scroll_area.setWidget(form_widget)
        layout.addWidget(scroll_area)
        
        self.tab_widget.addTab(summary_widget, "Summary")

    def _create_security_tab(self):
        """Create security/encryption details tab"""
        security_widget = QWidget()
        layout = QVBoxLayout(security_widget)
        
        # Encryption status group
        enc_group = QGroupBox("Encryption Status")
        enc_layout = QFormLayout(enc_group)
        
        enc_status = self.metadata.get('encryption_status', {})
        enc_layout.addRow("Master Key Provided:", 
                         QLabel("✓ Yes" if enc_status.get('master_key_provided') else "✗ No"))
        enc_layout.addRow("Session Key Generated:", 
                         QLabel("✓ Yes" if enc_status.get('session_key_generated') else "✗ No"))
        
        # Files encryption status
        encrypted_files = [f for f in self.metadata.get('file_manifest', []) 
                          if f.get('encrypted_counterpart')]
        enc_layout.addRow("Encrypted Files:", QLabel(f"{len(encrypted_files)} files"))
        
        layout.addWidget(enc_group)
        
        # PHI/PII Detection group
        phi_group = QGroupBox("PHI/PII Protection")
        phi_layout = QVBoxLayout(phi_group)
        
        # PHI/PII table
        phi_table = QTableWidget()
        phi_instances = self.metadata.get('phi_pii_detected_in_transcript', [])
        
        if phi_instances:
            phi_table.setColumnCount(4)
            phi_table.setHorizontalHeaderLabels(["Text", "Type", "Position", "Confidence"])
            phi_table.setRowCount(len(phi_instances))
            
            for i, instance in enumerate(phi_instances):
                phi_table.setItem(i, 0, QTableWidgetItem(instance.get('text', '')))
                phi_table.setItem(i, 1, QTableWidgetItem(instance.get('entity_type', '')))
                phi_table.setItem(i, 2, QTableWidgetItem(f"{instance.get('start', '')}-{instance.get('end', '')}"))
                phi_table.setItem(i, 3, QTableWidgetItem(f"{instance.get('score', 0):.2f}"))
            
            phi_table.horizontalHeader().setStretchLastSection(True)
            phi_table.setMaximumHeight(150)
        else:
            phi_table.setRowCount(1)
            phi_table.setColumnCount(1)
            phi_table.setItem(0, 0, QTableWidgetItem("No PHI/PII detected"))
        
        phi_layout.addWidget(phi_table)
        layout.addWidget(phi_group)
        
        layout.addStretch()
        self.tab_widget.addTab(security_widget, "Security")

    def _create_speakers_tab(self):
        """Create speakers analysis tab"""
        speakers_widget = QWidget()
        layout = QVBoxLayout(speakers_widget)
        
        diar_summary = self.metadata.get('diarization_summary', {})
        speakers = diar_summary.get('speakers_identified', [])
        voice_prints = diar_summary.get('num_voice_prints_collected_per_speaker', {})
        ai_consents = self.metadata.get('ai_training_consent_per_speaker', {})
        
        if speakers:
            # Speakers table
            speakers_table = QTableWidget()
            speakers_table.setColumnCount(3)
            speakers_table.setHorizontalHeaderLabels(["Speaker ID", "Voice Prints", "AI Consent"])
            speakers_table.setRowCount(len(speakers))
            
            for i, speaker in enumerate(speakers):
                speakers_table.setItem(i, 0, QTableWidgetItem(speaker))
                vp_count = voice_prints.get(speaker, 0)
                speakers_table.setItem(i, 1, QTableWidgetItem(str(vp_count)))
                consent = ai_consents.get(speaker, False)
                consent_text = "✓ Yes" if consent else "✗ No"
                speakers_table.setItem(i, 2, QTableWidgetItem(consent_text))
            
            speakers_table.horizontalHeader().setStretchLastSection(True)
            speakers_table.resizeColumnsToContents()
            layout.addWidget(speakers_table)
            
            # Summary stats
            total_vp = sum(voice_prints.values())
            consented_count = sum(1 for c in ai_consents.values() if c)
            
            stats_label = QLabel(f"""
            <b>Summary:</b><br>
            • Total Speakers: {len(speakers)}<br>
            • Total Voice Prints: {total_vp}<br>
            • AI Training Consents: {consented_count}/{len(speakers)}
            """)
            layout.addWidget(stats_label)
        else:
            layout.addWidget(QLabel("No speakers identified in this session."))
        
        layout.addStretch()
        self.tab_widget.addTab(speakers_widget, "Speakers")

    def _create_files_tab(self):
        """Create files manifest tab"""
        files_widget = QWidget()
        layout = QVBoxLayout(files_widget)
        
        file_manifest = self.metadata.get('file_manifest', [])
        
        if file_manifest:
            files_table = QTableWidget()
            files_table.setColumnCount(4)
            files_table.setHorizontalHeaderLabels(["Filename", "Path", "Description", "Encrypted"])
            files_table.setRowCount(len(file_manifest))
            
            for i, file_info in enumerate(file_manifest):
                files_table.setItem(i, 0, QTableWidgetItem(file_info.get('filename', '')))
                files_table.setItem(i, 1, QTableWidgetItem(file_info.get('path', '')))
                files_table.setItem(i, 2, QTableWidgetItem(file_info.get('description', '')))
                encrypted = "✓ Yes" if file_info.get('encrypted_counterpart') else "✗ No"
                files_table.setItem(i, 3, QTableWidgetItem(encrypted))
            
            files_table.horizontalHeader().setStretchLastSection(True)
            files_table.resizeColumnsToContents()
            layout.addWidget(files_table)
        else:
            layout.addWidget(QLabel("No files listed in manifest."))
        
        layout.addStretch()
        self.tab_widget.addTab(files_widget, "Files")

    def _create_raw_metadata_tab(self):
        """Create raw metadata view tab"""
        metadata_widget = QWidget()
        layout = QVBoxLayout(metadata_widget)
        
        # Add search/filter controls here if needed
        controls_layout = QHBoxLayout()
        export_btn = QPushButton("Export Metadata")
        export_btn.clicked.connect(self._export_metadata)
        controls_layout.addWidget(export_btn)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Raw metadata display
        metadata_display = QTextEdit()
        metadata_display.setReadOnly(True)
        metadata_display.setFont(QFont("Courier", 9))
        
        try:
            formatted_json = json.dumps(self.metadata, indent=2, sort_keys=True, default=str)
            metadata_display.setText(formatted_json)
        except Exception as e:
            metadata_display.setText(f"Error formatting metadata: {e}\n\nRaw data:\n{str(self.metadata)}")
        
        layout.addWidget(metadata_display)
        self.tab_widget.addTab(metadata_widget, "Raw Metadata")

    def _create_footer(self, layout):
        """Create footer with action buttons"""
        button_layout = QHBoxLayout()
        
        # Export button
        export_btn = QPushButton("Export Summary")
        export_btn.clicked.connect(self._export_summary)
        button_layout.addWidget(export_btn)
        
        button_layout.addStretch()
        
        # Standard dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_layout.addWidget(button_box)
        
        layout.addLayout(button_layout)

    def _apply_styling(self):
        """Apply modern styling to the dialog"""
        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            QTabWidget::pane {
                border: 1px solid #dee2e6;
                background-color: white;
            }
            QTabBar::tab {
                background-color: #e9ecef;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 2px solid #007bff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #dee2e6;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QTableWidget {
                gridline-color: #dee2e6;
                background-color: white;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)

    # Helper methods
    def _calculate_duration(self):
        """Calculate and format session duration"""
        start_iso = self.metadata.get('session_start_time')
        end_iso = self.metadata.get('session_end_time')
        
        if not start_iso or not end_iso:
            return "N/A"
        
        try:
            start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
            
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            
            duration = end_dt - start_dt
            total_seconds = int(duration.total_seconds())
            
            if total_seconds < 0:
                return "Invalid (end before start)"
            
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
                
        except Exception as e:
            return f"Error: {str(e)}"

    def _format_timestamp(self, timestamp_str):
        """Format timestamp for display"""
        if not timestamp_str:
            return "N/A"
        
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        except:
            return timestamp_str

    def _is_encrypted(self):
        """Check if session uses encryption"""
        enc_status = self.metadata.get('encryption_status', {})
        return enc_status.get('master_key_provided', False)

    def _get_consent_info(self):
        """Get formatted consent information"""
        consent = self.metadata.get('initial_recording_consent', {})
        if not consent.get('consent_given'):
            return "Not Given"
        
        expires = consent.get('expires_timestamp', 'N/A')
        try:
            if expires != 'N/A':
                expires_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                expires = expires_dt.strftime('%Y-%m-%d')
        except:
            pass
        
        return f"Given (Expires: {expires})"

    def _get_ai_consent_info(self):
        """Get AI training consent summary"""
        consents = self.metadata.get('ai_training_consent_per_speaker', {})
        if not consents:
            return "N/A"
        
        if isinstance(consents, str):
            return consents
        
        consented = sum(1 for v in consents.values() if v)
        return f"{consented} of {len(consents)} speakers consented"

    def _get_emotions_info(self):
        """Get emotions summary"""
        emotions = self.metadata.get('emotion_annotations', [])
        if not emotions:
            return "Not processed"
        
        unique_emotions = set(
            ann.get('dominant_emotion') for ann in emotions
            if isinstance(ann, dict) and ann.get('dominant_emotion')
        )
        
        return ", ".join(sorted(unique_emotions)) if unique_emotions else "None detected"

    def _export_summary(self):
        """Export session summary to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Session Summary", 
            f"session_summary_{self.metadata.get('session_id', 'unknown')}.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self._generate_text_summary())
                QMessageBox.information(self, "Export Successful", f"Summary exported to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Failed to export summary: {str(e)}")

    def _export_metadata(self):
        """Export raw metadata to JSON file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Metadata", 
            f"metadata_{self.metadata.get('session_id', 'unknown')}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(self.metadata, f, indent=2, default=str)
                QMessageBox.information(self, "Export Successful", f"Metadata exported to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Failed to export metadata: {str(e)}")

    def _generate_text_summary(self):
        """Generate plain text summary"""
        summary = f"""
SESSION SUMMARY REPORT
=====================

Session ID: {self.metadata.get('session_id', 'N/A')}
Duration: {self._calculate_duration()}
Start Time: {self._format_timestamp(self.metadata.get('session_start_time'))}
End Time: {self._format_timestamp(self.metadata.get('session_end_time'))}

SECURITY & CONSENT
------------------
Encryption: {'Enabled' if self._is_encrypted() else 'Disabled'}
Recording Consent: {self._get_consent_info()}
AI Training Consents: {self._get_ai_consent_info()}

SPEAKERS & ANALYSIS
-------------------
Speakers Identified: {len(self.metadata.get('diarization_summary', {}).get('speakers_identified', []))}
Total Voice Prints: {sum(self.metadata.get('diarization_summary', {}).get('num_voice_prints_collected_per_speaker', {}).values())}
Dominant Emotions: {self._get_emotions_info()}

PRIVACY PROTECTION
------------------
PHI/PII Instances Detected: {len(self.metadata.get('phi_pii_detected_in_transcript', []))}
Audio Segments Muted: {len(self.metadata.get('phi_pii_audio_mute_segments', []))}

FILES
-----
Total Files: {len(self.metadata.get('file_manifest', []))}
Encrypted Files: {len([f for f in self.metadata.get('file_manifest', []) if f.get('encrypted_counterpart')])}

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()
        
        return summary


if __name__ == '__main__':
    app = QApplication(sys.argv)

    now_iso = datetime.now(timezone.utc).isoformat()
    later_iso = (datetime.now(timezone.utc) + timedelta(minutes=2, seconds=15)).isoformat()
    expiry_iso = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

    sample_metadata = {
        'session_id': "ENHANCED_SESSION_20231028_120000",
        'session_start_time': now_iso,
        'session_end_time': later_iso,
        'encryption_status': {
            'master_key_provided': True,
            'session_key_generated': True,
            'files_encrypted': True
        },
        'initial_recording_consent': {
            'consent_given': True,
            'timestamp': now_iso,
            'expires_timestamp': expiry_iso
        },
        'ai_training_consent_per_speaker': {
            "SPEAKER_00": True,
            "SPEAKER_01": False,
            "SPEAKER_02": True
        },
        'diarization_summary': {
            'speakers_identified': ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"],
            'num_voice_prints_collected_per_speaker': {"SPEAKER_00": 2, "SPEAKER_01": 1, "SPEAKER_02": 3}
        },
        'voice_print_file_references': {
            "SPEAKER_00": ["standard/voice_embeddings/SPEAKER_00_emb_0.npy", "standard/voice_embeddings/SPEAKER_00_emb_1.npy"],
            "SPEAKER_01": ["standard/voice_embeddings/SPEAKER_01_emb_0.npy"],
            "SPEAKER_02": ["standard/voice_embeddings/SPEAKER_02_emb_0.npy", "standard/voice_embeddings/SPEAKER_02_emb_1.npy", "standard/voice_embeddings/SPEAKER_02_emb_2.npy"]
        },
        'phi_pii_detected_in_transcript': [
            {'text': 'John Doe', 'entity_type': 'PERSON', 'start': 10, 'end': 18, 'score': 0.95},
            {'text': '555-123-4567', 'entity_type': 'PHONE_NUMBER', 'start': 45, 'end': 57, 'score': 0.98},
            {'text': 'john.doe@email.com', 'entity_type': 'EMAIL', 'start': 80, 'end': 98, 'score': 0.92}
        ],
        'phi_pii_audio_mute_segments': [
            {'start_time_seconds': 12.34, 'end_time_seconds': 13.01},
            {'start_time_seconds': 45.2, 'end_time_seconds': 46.8}
        ],
        'emotion_annotations': [
            {'segment_start_time_seconds': 10.0, 'dominant_emotion': 'neutral', 'score': 0.7, 'all_predictions': [{'label': 'neutral', 'score': 0.7}]},
            {'segment_start_time_seconds': 20.0, 'dominant_emotion': 'happy', 'score': 0.85, 'all_predictions': [{'label': 'happy', 'score': 0.85}]},
            {'segment_start_time_seconds': 30.0, 'dominant_emotion': 'confident', 'score': 0.6, 'all_predictions': [{'label': 'confident', 'score': 0.6}]}
        ],
        'file_manifest': [
            {'filename': 'full_audio.wav', 'path': 'standard/full_audio.wav', 'description': 'Original full audio recording', 'encrypted_counterpart': 'encrypted/full_audio.wav.enc'},
            {'filename': 'transcript.txt', 'path': 'standard/transcript.txt', 'description': 'Full session transcript', 'encrypted_counterpart': 'encrypted/transcript.txt.enc'},
            {'filename': 'metadata.json', 'path': 'standard/metadata.json', 'description': 'Session metadata file', 'encrypted_counterpart': 'encrypted/metadata.json.enc'}
        ],
        'audit_log_file_references': "standard/audit.log"
    }

    dialog = SessionSummaryDialog(metadata_dict=sample_metadata)
    result = dialog.exec_()

    if result == QDialog.Accepted:
        print("Summary dialog accepted (closed via OK).")
    else:
        print(f"Summary dialog closed/rejected (result code: {result}).")

    sys.exit(0)