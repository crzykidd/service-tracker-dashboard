import logging
import requests
from collections import defaultdict

logger = logging.getLogger(__name__)

def fetch_widget_data(api_url, api_key, widget_fields, available_fields):
    logger.info(f"📢 Entered fetch_widget_data for {api_url}")
    headers = {"X-Api-Key": api_key}
    results = {}

    # Step 1: Map widget field keys to full field definitions
    key_to_field = {f["key"]: f for f in available_fields if f["key"] in widget_fields}

    # Step 2: Group field keys by api_path
    path_to_keys = defaultdict(list)
    for key, field in key_to_field.items():
        path = field.get("api_path")
        if path:
            path_to_keys[path].append(key)

    # Step 3: Fetch each unique endpoint once
    for path, keys in path_to_keys.items():
        full_url = f"{api_url.rstrip('/')}{path}"
        try:
            logger.debug(f"📡 Requesting {full_url} for keys: {keys}")
            response = requests.get(full_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            for key in keys:
                field = key_to_field[key]
                value_path = field.get("response_path")
                value = data.get(value_path) if isinstance(data, dict) else None

                results[key] = value
                logger.info(f"✅ Field '{key}' value: {results[key]}")

        except Exception as e:
            logger.error(f"❌ Failed to fetch {full_url} for fields {keys}: {e}")
            for key in keys:
                results[key] = f"error: {str(e)}"

    return results
