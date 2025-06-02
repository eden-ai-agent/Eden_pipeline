import sys
import json
from datetime import datetime, timezone # Added timezone for robust ISO parsing
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QScrollArea, QWidget,
    QFormLayout, QDialogButtonBox, QTextEdit, QApplication
)
from PyQt5.QtCore import Qt

class SessionSummaryDialog(QDialog):
    def __init__(self, metadata_dict: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Summary & Metadata")
        self.metadata = metadata_dict

        main_layout = QVBoxLayout(self)

        # --- Summary Section ---
        summary_group_label = QLabel("<b>Session Summary:</b>")
        main_layout.addWidget(summary_group_label)

        # ScrollArea for the form layout in case of many items
        form_scroll_area = QScrollArea()
        form_scroll_area.setWidgetResizable(True)
        form_scroll_area.setMinimumHeight(200) # Ensure it's not too small

        form_widget = QWidget() # Content widget for QScrollArea
        form_layout = QFormLayout(form_widget) # FormLayout inside the content widget
        form_layout.setContentsMargins(10, 5, 10, 5)
        form_layout.setLabelAlignment(Qt.AlignRight)
        form_layout.setRowWrapPolicy(QFormLayout.WrapAllRows) # Helps with long labels/values

        # Session ID
        form_layout.addRow("Session ID:", QLabel(str(self.metadata.get('session_id', 'N/A'))))

        # Session Duration
        start_iso = self.metadata.get('session_start_time')
        end_iso = self.metadata.get('session_end_time')
        duration_str = "N/A"
        if start_iso and end_iso:
            try:
                # Ensure timestamps are offset-aware if they include 'Z' or offset info
                start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
                if start_dt.tzinfo is None: start_dt = start_dt.replace(tzinfo=timezone.utc)
                if end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)

                duration = end_dt - start_dt
                total_seconds = int(duration.total_seconds())
                if total_seconds < 0:
                    duration_str = "Invalid (end before start)"
                else:
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    if minutes > 0:
                        duration_str = f"{minutes} minute(s), {seconds} second(s)"
                    else:
                        duration_str = f"{seconds} second(s)"
            except ValueError as ve:
                print(f"Error parsing session times for duration: {ve}")
                duration_str = "Error calculating duration"
        form_layout.addRow("Session Duration:", QLabel(duration_str))

        # Encryption Status
        enc_status_dict = self.metadata.get('encryption_status', {})
        files_encrypted_flag = any(
            file_entry.get('encrypted_counterpart')
            for file_entry in self.metadata.get('file_manifest', [])
            if file_entry.get('filename') != "session_key.key.enc" # Don't count the key itself as an encrypted file for this summary
        ) or (enc_status_dict.get('master_key_provided') and enc_status_dict.get('session_key_generated') and len(self.metadata.get('file_manifest', [])) > 1)


        enc_text = "Disabled (No Master Key)"
        if enc_status_dict.get('master_key_provided'):
            if files_encrypted_flag:
                enc_text = "Enabled (Files Encrypted)"
            else:
                enc_text = "Enabled (Master Key Provided, but no files marked as encrypted or no files to encrypt)"
        form_layout.addRow("File Encryption Status:", QLabel(enc_text))

        # Initial Consent
        init_consent_dict = self.metadata.get('initial_recording_consent', {})
        consent_text = "Not Given"
        if init_consent_dict.get('consent_given'):
            expires_ts = init_consent_dict.get('expires_timestamp', 'N/A')
            try:
                if expires_ts != 'N/A': expires_ts = datetime.fromisoformat(expires_ts.replace('Z', '+00:00')).strftime('%Y-%m-%d')
            except: pass # Keep as N/A if format error
            consent_text = f"Given (Expires: {expires_ts})"
        form_layout.addRow("Initial Recording Consent:", QLabel(consent_text))

        # Speakers Identified
        diar_summary = self.metadata.get('diarization_summary', {})
        speakers_list = diar_summary.get('speakers_identified', [])
        form_layout.addRow("Unique Speakers Identified:", QLabel(str(len(speakers_list))))

        # PHI/PII Instances
        phi_list = self.metadata.get('phi_pii_detected_in_transcript', [])
        form_layout.addRow("PHI/PII Text Instances Detected:", QLabel(str(len(phi_list))))

        mute_segments = self.metadata.get('phi_pii_audio_mute_segments', [])
        form_layout.addRow("Audio Segments Muted for PII:", QLabel(str(len(mute_segments))))

        # AI Training Consents
        ai_consents = self.metadata.get('ai_training_consent_per_speaker', {})
        ai_consent_summary_text = "N/A (No speakers or consent not solicited)"
        if isinstance(ai_consents, dict) and ai_consents:
            num_consented = sum(1 for v in ai_consents.values() if v)
            ai_consent_summary_text = f"{num_consented} of {len(ai_consents)} speakers consented."
        elif isinstance(ai_consents, str) and ai_consents:
             ai_consent_summary_text = ai_consents
        form_layout.addRow("AI Training Consents:", QLabel(ai_consent_summary_text))

        # Voice Prints Collected
        vp_per_speaker = diar_summary.get('num_voice_prints_collected_per_speaker', {})
        form_layout.addRow("Total Voice Prints Collected:", QLabel(str(sum(vp_per_speaker.values()))))

        # Dominant Emotions
        emotions_data = self.metadata.get('emotion_annotations', [])
        emotions_str = "Not processed or no emotions detected"
        if emotions_data:
            unique_emotions = sorted(list(set(
                ann['dominant_emotion'] for ann in emotions_data
                if isinstance(ann, dict) and 'dominant_emotion' in ann
            )))
            emotions_str = ", ".join(unique_emotions) if unique_emotions else "None detected"
        form_layout.addRow("Dominant Emotions (across session):", QLabel(emotions_str))

        form_widget.setLayout(form_layout)
        form_scroll_area.setWidget(form_widget)
        main_layout.addWidget(form_scroll_area)

        # --- Raw Metadata Preview Section ---
        preview_label = QLabel("<b>Full Metadata Preview (metadata.json content):</b>")
        main_layout.addWidget(preview_label)

        metadata_preview = QTextEdit()
        metadata_preview.setReadOnly(True)
        try:
            metadata_preview.setText(json.dumps(self.metadata, indent=4, sort_keys=True))
        except TypeError as te:
            metadata_preview.setText(f"Error serializing metadata for preview: {te}\n\nAttempting to display raw: {str(self.metadata)}")
        metadata_preview.setFixedHeight(200)
        metadata_preview.setLineWrapMode(QTextEdit.NoWrap)

        main_layout.addWidget(metadata_preview)

        # --- Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        main_layout.addWidget(button_box)

        self.setLayout(main_layout)
        self.resize(550, 650)


if __name__ == '__main__':
    app = QApplication(sys.argv)

    now_iso = datetime.now(timezone.utc).isoformat()
    later_iso = (datetime.now(timezone.utc) + datetime.timedelta(minutes=2, seconds=15)).isoformat()
    expiry_iso = (datetime.now(timezone.utc) + datetime.timedelta(days=365)).isoformat()

    sample_metadata = {
        'session_id': "TEST_SESSION_20231028_120000",
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
            {'text': 'John Doe', 'entity_type': 'PERSON', 'start': 10, 'end': 18, 'score': 0.95}
        ],
        'phi_pii_audio_mute_segments': [
            {'start_time_seconds': 12.34, 'end_time_seconds': 13.01}
        ],
        'emotion_annotations': [
            {'segment_start_time_seconds': 10.0, 'dominant_emotion': 'neutral', 'score': 0.7, 'all_predictions': [{'label': 'neutral', 'score': 0.7}]},
            {'segment_start_time_seconds': 20..0, 'dominant_emotion': 'happy', 'score': 0.85, 'all_predictions': [{'label': 'happy', 'score': 0.85}]},
            {'segment_start_time_seconds': 30.0, 'dominant_emotion': 'neutral', 'score': 0.6, 'all_predictions': [{'label': 'neutral', 'score': 0.6}]}
        ],
        'file_manifest': [
            {'filename': 'full_audio.wav', 'path': 'standard/full_audio.wav', 'description': 'Original full audio recording', 'encrypted_counterpart': 'encrypted/full_audio.wav.enc'},
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
