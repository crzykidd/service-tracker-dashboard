import logging
import requests
from collections import defaultdict

logger = logging.getLogger(__name__)

def fetch_widget_data(api_url, api_key, widget_fields, available_fields):
    logger.info(f"📢 Entered fetch_widget_data for {api_url}")
    headers = {"X-Api-Key": api_key}
    results = {}

    # Step 1: Map fields to their API paths
    field_to_path = {}
    for field in available_fields:
        if field["key"] in widget_fields:
            field_to_path[field["key"]] = field.get("api_path")

    logger.debug(f"🔍 Fetching Radarr data for fields: {widget_fields}")

    # Step 2: Group fields by endpoint
    path_to_fields = defaultdict(list)
    for field, path in field_to_path.items():
        path_to_fields[path].append(field)

    # Step 3: Fetch each unique endpoint
    for path, fields in path_to_fields.items():
        full_url = f"{api_url.rstrip('/')}{path}"
        try:
            logger.debug(f"📡 Requesting {full_url} for fields: {fields}")
            response = requests.get(full_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            for field in fields:
                if field == "wanted":
                    results[field] = data.get("totalRecords") if isinstance(data, dict) else None
                elif field == "queued":
                    results[field] = data.get("totalRecords") if isinstance(data, dict) else None
                elif field == "movies":
                    results[field] = len(data) if isinstance(data, list) else None
                else:
                    logger.warning(f"⚠️ Unhandled field: {field}")
                    results[field] = None

                logger.info(f"✅ Field '{field}' value: {results[field]}")

        except Exception as e:
            logger.error(f"❌ Failed to fetch {full_url} for fields {fields}: {e}")
            for field in fields:
                results[field] = f"error: {str(e)}"

    return results
