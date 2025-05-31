import os
import shutil
import yaml

CONFIG_PATH = "/config/settings.yml"
DEFAULT_TEMPLATE = "settings.example.yml"

# Define the expected config keys and their types
VALID_KEYS = {
    "backup_path": str,
    "api_token": str,
    "std_dozzle_url": str,
}

def load_settings():
    # Ensure settings.yml exists
    if not os.path.exists(CONFIG_PATH):
        shutil.copy(DEFAULT_TEMPLATE, CONFIG_PATH)

    # Load from settings.yml
    with open(CONFIG_PATH, "r") as f:
        file_config = yaml.safe_load(f) or {}

    final_config = {}

    # Merge ENV > YAML > None
    for key, expected_type in VALID_KEYS.items():
        env_val = os.getenv(key.upper())
        if env_val is not None:
            # Cast types if necessary (expand later for booleans/ints)
            final_config[key] = expected_type(env_val)
        else:
            final_config[key] = file_config.get(key)

    return final_config
