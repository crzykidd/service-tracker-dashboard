import os
import shutil
import yaml

CONFIG_PATH = "/config/settings.yml"
DEFAULT_TEMPLATE = "settings.example.yml"

# Define the expected config keys and their types
VALID_KEYS = {
    "backup_path": str,
    "backup_days_to_keep": int,
    "api_token": str,
    "std_dozzle_url": str,
    "url_healthcheck_interval": int
}

def load_settings():
    if not os.path.exists(CONFIG_PATH):
        shutil.copy(DEFAULT_TEMPLATE, CONFIG_PATH)

    with open(CONFIG_PATH, "r") as f:
        file_config = yaml.safe_load(f) or {}

    final_config = {}
    config_from_env = {}
    config_from_file = {}

    for key, expected_type in VALID_KEYS.items():
        env_val = os.getenv(key.upper())
        if env_val is not None:
            final_config[key] = expected_type(env_val)
            config_from_env[key] = True
        elif key in file_config:
            final_config[key] = file_config[key]
            config_from_file[key] = True
        else:
            final_config[key] = None  # Or a default fallback

    return final_config, config_from_env, config_from_file
