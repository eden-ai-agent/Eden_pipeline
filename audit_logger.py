import datetime
import json
import os

class AuditLogger:
    def __init__(self, log_filepath: str):
        """
        Initializes the AuditLogger.
        :param log_filepath: Path to the audit log file.
        """
        self.log_filepath = log_filepath
        try:
            # Ensure the directory for the log file exists
            log_dir = os.path.dirname(self.log_filepath)
            if log_dir and not os.path.exists(log_dir): # Check if log_dir is not empty (e.g. for relative paths)
                os.makedirs(log_dir, exist_ok=True)

            # Touch the file to ensure it's creatable/writable, and it exists for append operations
            with open(self.log_filepath, 'a', encoding='utf-8') as f:
                pass # File created if it didn't exist, or opened if it did.
        except Exception as e:
            # This is a critical error if the logger can't be initialized.
            # Depending on application policy, this might need to halt startup.
            print(f"CRITICAL: AuditLogger failed to initialize log file at {self.log_filepath}: {e}")
            # raise # Optionally re-raise to signal failure to the application

    def log_action(self, action_type: str, details: dict = None):
        """
        Logs an action with a timestamp and optional details.
        :param action_type: A string describing the type of action (e.g., "USER_LOGIN", "FILE_ENCRYPTED").
        :param details: A dictionary containing additional structured information about the event.
        """
        try:
            # Ensure timestamp is always UTC and in ISO format
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

            log_entry = {
                "timestamp": timestamp,
                "action": action_type
            }

            if details is not None and isinstance(details, dict):
                log_entry.update(details)

            # Convert the log entry dictionary to a JSON string
            log_line = json.dumps(log_entry, ensure_ascii=False) # ensure_ascii=False for better UTF-8 handling

            # Append the JSON string as a new line to the log file
            with open(self.log_filepath, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')

        except Exception as e:
            # Log to console if file logging fails, to not lose the audit trail completely.
            print(f"ERROR: Failed to write to audit log file {self.log_filepath}. Log Entry: {log_entry if 'log_entry' in locals() else 'Unknown'}. Error: {e}")
            # Depending on policy, could try a fallback log or raise an alert.

if __name__ == '__main__':
    print("--- Testing AuditLogger ---")
    test_log_filename = "test_audit.log"

    # Ensure no old test file exists
    if os.path.exists(test_log_filename):
        os.remove(test_log_filename)

    logger = AuditLogger(log_filepath=test_log_filename)

    # Test log actions
    logger.log_action("APP_START", {"version": "1.0.0", "user_id": "system"})
    logger.log_action("USER_CONSENT_GIVEN", {"session_id": "sess_001", "consent_type": "recording"})
    logger.log_action("RECORDING_STARTED", {"session_id": "sess_001", "device": "default_mic"})
    logger.log_action("PII_DETECTED", {"session_id": "sess_001", "entity_type": "PERSON", "count": 2})
    logger.log_action("FILE_SAVED", {"session_id": "sess_001", "filename": "full_audio.wav", "path": "standard/full_audio.wav"})
    logger.log_action("FILE_ENCRYPTED", {"session_id": "sess_001", "filename": "full_audio.wav.enc", "algorithm": "AES-GCM"})
    logger.log_action("RECORDING_STOPPED", {"session_id": "sess_001", "duration_seconds": 125.5})
    logger.log_action("APP_SHUTDOWN")

    print(f"Test log actions written to '{test_log_filename}'.")

    # Verify content
    try:
        with open(test_log_filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if len(lines) == 8: # Should be 8 log entries
            print("Audit log file content verification: Number of lines is correct.")
            # Further checks could parse JSON and validate content
            first_entry = json.loads(lines[0])
            if first_entry["action"] == "APP_START" and first_entry["details"]["version"] == "1.0.0":
                print("First log entry content seems correct.")
            else:
                print("First log entry content mismatch.")
        else:
            print(f"Audit log file content verification: Incorrect number of lines. Expected 8, got {len(lines)}.")

    except Exception as e:
        print(f"Error reading or verifying audit log file: {e}")

    finally:
        # Clean up the test log file
        if os.path.exists(test_log_filename):
            # os.remove(test_log_filename) # Keep it for inspection if needed during manual test
            print(f"Test log file '{test_log_filename}' is available for inspection.")
            # For automated tests, uncomment os.remove()

    print("\n--- AuditLogger Test Finished ---")
