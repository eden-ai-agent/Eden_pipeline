import datetime
import json
import os
import logging # Added

# Get a logger instance for this module.
# It will inherit the configuration from the root logger if app.py (or another entry point)
# has already configured logging. If this module is run standalone or imported first,
# this logger might not output as expected until logging is configured.
module_logger = logging.getLogger(__name__)

class AuditLogger:
    def __init__(self, log_filepath: str):
        """
        Initializes the AuditLogger.
        :param log_filepath: Path to the audit log file.
        """
        self.log_filepath = log_filepath
        try:
            log_dir = os.path.dirname(self.log_filepath)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            with open(self.log_filepath, 'a', encoding='utf-8') as f:
                pass
        except Exception as e:
            # Use the module_logger for this critical initialization error.
            module_logger.critical(f"AuditLogger failed to initialize log file at {self.log_filepath}: {e}", exc_info=True)
            # Optionally re-raise if the application should not continue without a working audit log.
            # raise

    def log_action(self, action_type: str, details: dict = None):
        """
        Logs an action with a timestamp and optional details.
        :param action_type: A string describing the type of action (e.g., "USER_LOGIN", "FILE_ENCRYPTED").
        :param details: A dictionary containing additional structured information about the event.
        """
        log_entry = {} # Initialize in case of early failure
        try:
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            log_entry = {
                "timestamp": timestamp,
                "action": action_type
            }
            if details is not None and isinstance(details, dict):
                # Create a new dictionary for the log entry to avoid modifying the original 'details'
                # if it's passed around and used elsewhere.
                current_entry_details = details.copy()
                log_entry["details"] = current_entry_details # Store details under a 'details' key

            log_line = json.dumps(log_entry, ensure_ascii=False)

            with open(self.log_filepath, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')

        except Exception as e:
            # Use the module_logger if writing to the audit file fails.
            # Include the log_entry that failed to be written.
            module_logger.error(f"Failed to write to audit log file {self.log_filepath}. Log Entry: {log_entry}. Error: {e}", exc_info=True)


if __name__ == '__main__':
    # Basic logging configuration for standalone testing of audit_logger.py
    # This will print to console. If app.py runs this, app.py's config will be used.
    if not logging.getLogger().handlers: # Check if root logger has no handlers
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    module_logger.info("--- Testing AuditLogger ---")
    test_log_filename = "test_audit.log"

    if os.path.exists(test_log_filename):
        os.remove(test_log_filename)
        module_logger.info(f"Removed old test log file: {test_log_filename}")

    # Initialize AuditLogger instance for testing
    # Note: The critical log inside AuditLogger.__init__ might not show in console
    # if this script is run standalone and the init fails, unless basicConfig is called before instantiation.
    # However, for this test, we assume initialization is successful.
    audit_trail_logger = AuditLogger(log_filepath=test_log_filename)

    module_logger.info("Logging test actions...")
    audit_trail_logger.log_action("APP_START", {"version": "1.0.0", "user_id": "system_test"})
    audit_trail_logger.log_action("USER_CONSENT_GIVEN", {"session_id": "sess_test_001", "consent_type": "recording"})
    audit_trail_logger.log_action("RECORDING_STARTED", {"session_id": "sess_test_001", "device": "default_mic_test"})
    audit_trail_logger.log_action("PII_DETECTED", {"session_id": "sess_test_001", "entity_type": "PERSON_TEST", "count": 2})
    audit_trail_logger.log_action("FILE_SAVED", {"session_id": "sess_test_001", "filename": "test_audio.wav", "path": "standard/test_audio.wav"})
    audit_trail_logger.log_action("FILE_ENCRYPTED", {"session_id": "sess_test_001", "filename": "test_audio.wav.enc", "algorithm": "AES-GCM_TEST"})
    audit_trail_logger.log_action("RECORDING_STOPPED", {"session_id": "sess_test_001", "duration_seconds": 125.5})
    audit_trail_logger.log_action("APP_SHUTDOWN_TEST")

    module_logger.info(f"Test log actions written to '{test_log_filename}'.")

    try:
        with open(test_log_filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if len(lines) == 8:
            module_logger.info("Audit log file content verification: Number of lines is correct.")
            first_entry = json.loads(lines[0])
            # Adjusted check for the new structure where details are nested
            if first_entry["action"] == "APP_START" and first_entry.get("details", {}).get("version") == "1.0.0":
                module_logger.info("First log entry content seems correct.")
            else:
                module_logger.error(f"First log entry content mismatch. Entry: {first_entry}")
        else:
            module_logger.error(f"Audit log file content verification: Incorrect number of lines. Expected 8, got {len(lines)}.")

    except Exception as e:
        module_logger.error(f"Error reading or verifying audit log file: {e}", exc_info=True)
    finally:
        if os.path.exists(test_log_filename):
            module_logger.info(f"Test log file '{test_log_filename}' is available for inspection. For automated tests, it would typically be removed.")
            # os.remove(test_log_filename)

    module_logger.info("\n--- AuditLogger Test Finished ---")
