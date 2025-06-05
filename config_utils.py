import json
import os

CONFIG_FILE_PATH = "config.json"
DEFAULT_CONFIG = {
    "sessions_output_dir": "sessions_output",
    "app_log_file": "logs/app.log",
    "audit_log_dir": "logs"
}

def load_or_create_config(config_path, defaults):
    loaded_config = {}
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f: # Specify encoding
                loaded_config = json.load(f)
        else:
            # Using print here as logger might not be configured yet,
            # or could even depend on this config loading.
            print(f"INFO: Configuration file '{config_path}' not found, creating with defaults.")
    except json.JSONDecodeError as e: # Specific exception for JSON parsing
        print(f"WARNING: Error decoding JSON from '{config_path}': {e}. Using defaults and attempting to overwrite.")
        loaded_config = {}
    except (IOError, OSError) as e: # Specific for file I/O issues
        print(f"WARNING: File I/O error loading config '{config_path}': {e}. Using defaults.")
        loaded_config = {}
    except Exception as e: # General fallback
        print(f"WARNING: An unexpected error occurred loading config '{config_path}': {e}. Using defaults.")
        loaded_config = {}

    config_to_save = defaults.copy()
    config_to_save.update(loaded_config) # loaded_config values overwrite default values if keys match

    try:
        config_dir = os.path.dirname(config_path)
        if config_dir and not os.path.exists(config_dir): # Ensure directory for config file exists
            os.makedirs(config_dir, exist_ok=True)

        with open(config_path, 'w', encoding='utf-8') as f: # Specify encoding
            json.dump(config_to_save, f, indent=4)
    except (IOError, OSError) as e: # Specific for file I/O issues
        print(f"CRITICAL: Could not write configuration file to '{config_path}' due to I/O error: {e}")
        # Fallback to in-memory defaults if write fails, app might still be partially functional
        return defaults
    except TypeError as e: # Specific for json.dump if config_to_save is not serializable
        print(f"CRITICAL: Could not serialize configuration to JSON for '{config_path}': {e}")
        return defaults
    except Exception as e: # General fallback
        print(f"CRITICAL: An unexpected error occurred writing configuration to '{config_path}': {e}")
        return defaults

    return config_to_save
