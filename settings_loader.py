import logging
import os
import shutil

import yaml

# Directory holding settings.yml, the DB, logs, images and backups. Defaults to
# /config (the container mount). STD_CONFIG_DIR is a dev/test knob so the test
# suite can run against a temp dir; production leaves it unset.
CONFIG_DIR = os.environ.get("STD_CONFIG_DIR", "/config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.yml")
DEFAULT_TEMPLATE = "settings.example.yml"
EXAMPLE_DEST = os.path.join(CONFIG_DIR, "settings.example.yml")
# Configure logging
logger = logging.getLogger(__name__)


# Define the expected config keys and their types
VALID_KEYS = {
    "backup_path": str,
    "backup_days_to_keep": int,
    "api_token": str,
    "std_dozzle_url": str,
    "url_healthcheck_interval": int,
    "widget_background_reload": int,
    "user_session_length": int,
    "widget_value_retention_days": int,
    "register_field_ownership": str,
}

# Keys whose values must never be written to logs in clear text.
SECRET_KEYS = {"api_token"}


def mask_value(key, value):
    """Return a log-safe rendering of a setting value (secrets become ***)."""
    if key in SECRET_KEYS and value:
        return "***"
    return value

DEFAULT_VALUES = {
    "backup_path": os.path.join(CONFIG_DIR, "backups"),
    "backup_days_to_keep": 7,
    "url_healthcheck_interval": 300,
    "widget_background_reload": 900,
    "user_session_length": 120,
    "widget_value_retention_days": 30,
    "register_field_ownership": "user_wins",
}
def load_settings():
    file_config = {}

    # Always overwrite the example settings file for the user
    try:
        shutil.copy(DEFAULT_TEMPLATE, EXAMPLE_DEST)
        logger.debug(f"✅ Copied latest example settings to: {EXAMPLE_DEST}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to copy example settings file: {e}")

    # Handle optional settings.yml
    if not os.path.exists(CONFIG_PATH):
        logger.warning("⚠️ No settings.yml found. Proceeding with ENV vars and defaults only.")
    else:
        with open(CONFIG_PATH, "r") as f:
            file_config = yaml.safe_load(f) or {}

    final_config = {}
    config_from_env = {}
    config_from_file = {}

    logger.debug("ENV settings:")
    for key, expected_type in VALID_KEYS.items():
        env_val = os.getenv(key.upper())
        if env_val is not None:
            try:
                final_config[key] = expected_type(env_val)
                config_from_env[key] = final_config[key]
                logger.debug(f"  {key} = {mask_value(key, final_config[key])} (from ENV)")
            except ValueError:
                logger.warning(f"Invalid type for {key} from ENV. Expected {expected_type.__name__}")
        elif key in file_config:
            final_config[key] = file_config[key]
            config_from_file[key] = final_config[key]
        else:
            final_config[key] = DEFAULT_VALUES.get(key, None)
            logger.debug(f"  {key} = {mask_value(key, final_config[key])} (default fallback)")

    logger.debug("YAML settings:")
    for key, val in config_from_file.items():
        logger.debug(f"  {key} = {mask_value(key, val)} (from YAML)")

    logger.debug("Final settings set are:")
    for key, val in final_config.items():
        logger.debug(f"  {key} = {mask_value(key, val)}")

    # --- Derived settings ---
    final_config["display_tools"] = bool(final_config.get("std_dozzle_url"))
    logger.debug(f"display_tools = {final_config['display_tools']} (derived from std_dozzle_url)")

    return final_config, config_from_env, config_from_file

