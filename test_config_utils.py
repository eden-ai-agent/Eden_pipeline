import unittest
import os
import json

# Add the directory containing app.py to sys.path if test_app.py is in a different directory
# For this environment, assuming app.py is in the root or accessible.
# If app.py is in a subdirectory, adjust path: e.g., sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app_directory')))

from config_utils import load_or_create_config, DEFAULT_CONFIG, CONFIG_FILE_PATH as APP_CONFIG_FILE_PATH

# Use a specific test configuration file to avoid interfering with a real one.
# We use a different name for tests than the actual CONFIG_FILE_PATH from config_utils
# to ensure tests don't accidentally use/modify the real config file if it exists.
TEST_CONFIG_FILE_PATH = "test_config.json"

class TestConfigHandling(unittest.TestCase):

    def setUp(self):
        """Ensure the test config file does not exist before each test."""
        if os.path.exists(TEST_CONFIG_FILE_PATH):
            os.remove(TEST_CONFIG_FILE_PATH)

    def tearDown(self):
        """Clean up by removing the test config file after each test."""
        if os.path.exists(TEST_CONFIG_FILE_PATH):
            os.remove(TEST_CONFIG_FILE_PATH)

    def test_create_new_config(self):
        """Test creation of a new config file with default values."""
        self.assertFalse(os.path.exists(TEST_CONFIG_FILE_PATH), "Test config file should not exist at start.")

        config = load_or_create_config(TEST_CONFIG_FILE_PATH, DEFAULT_CONFIG)

        self.assertTrue(os.path.exists(TEST_CONFIG_FILE_PATH), "Config file was not created.")
        self.assertEqual(config, DEFAULT_CONFIG, "Returned config does not match defaults.")

        with open(TEST_CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            file_content = json.load(f)
        self.assertEqual(file_content, DEFAULT_CONFIG, "File content does not match defaults.")

    def test_load_existing_config(self):
        """Test loading an existing config file with some custom values."""
        custom_data = {
            "sessions_output_dir": "custom_sessions",
            "app_log_file": "custom_logs/app.log"
            # audit_log_dir is missing, so it should be picked from DEFAULT_CONFIG
        }

        # Prepare expected config: defaults updated with custom_data
        expected_config = DEFAULT_CONFIG.copy()
        expected_config.update(custom_data)

        with open(TEST_CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(custom_data, f)

        loaded_config = load_or_create_config(TEST_CONFIG_FILE_PATH, DEFAULT_CONFIG)

        self.assertEqual(loaded_config, expected_config, "Loaded config does not match expected merged config.")

        # Verify that the file now contains the merged configuration (defaults filled in)
        with open(TEST_CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            file_content = json.load(f)
        self.assertEqual(file_content, expected_config, "File content was not updated with defaults.")

    def test_load_corrupted_config_file(self):
        """Test loading a corrupted config file; it should revert to defaults and fix the file."""
        with open(TEST_CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            f.write("this is not json {}{") # Corrupted JSON

        config = load_or_create_config(TEST_CONFIG_FILE_PATH, DEFAULT_CONFIG)

        self.assertEqual(config, DEFAULT_CONFIG, "Config did not revert to defaults after corruption.")

        # Verify the corrupted file was overwritten with defaults
        self.assertTrue(os.path.exists(TEST_CONFIG_FILE_PATH), "Config file should exist after attempted load.")
        with open(TEST_CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            file_content = json.load(f)
        self.assertEqual(file_content, DEFAULT_CONFIG, "Corrupted file was not overwritten with defaults.")

    def test_config_updates_with_new_default_keys(self):
        """Test that an old config file is updated with new keys from DEFAULT_CONFIG."""
        old_config_data = {
            "sessions_output_dir": "old_sessions"
            # "app_log_file" and "audit_log_dir" are missing from this old config
        }

        # Expected: old_config_data merged with any missing keys from DEFAULT_CONFIG
        expected_config = DEFAULT_CONFIG.copy()
        expected_config["sessions_output_dir"] = "old_sessions"

        with open(TEST_CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(old_config_data, f)

        config = load_or_create_config(TEST_CONFIG_FILE_PATH, DEFAULT_CONFIG)

        self.assertEqual(config, expected_config, "Config was not updated correctly with new default keys.")

        with open(TEST_CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            file_content = json.load(f)
        self.assertEqual(file_content, expected_config, "File content was not updated with new default keys.")

    def test_empty_existing_config_file(self):
        """Test loading an empty (but valid JSON) config file."""
        # An empty file is not valid JSON. A file with "{}" is valid.
        # Let's test with an empty JSON object.
        empty_json_data = {}
        with open(TEST_CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(empty_json_data, f)

        config = load_or_create_config(TEST_CONFIG_FILE_PATH, DEFAULT_CONFIG)

        # Expect it to be filled with defaults
        self.assertEqual(config, DEFAULT_CONFIG, "Config with empty JSON object did not fill with defaults.")

        with open(TEST_CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            file_content = json.load(f)
        self.assertEqual(file_content, DEFAULT_CONFIG, "File content for empty JSON object was not updated with defaults.")


if __name__ == '__main__':
    unittest.main()
