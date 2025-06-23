import logging
import requests

logger = logging.getLogger(__name__)

def fetch_widget_data(api_url, api_key, widget_fields, available_fields):
    logger.info(f"📢 Entered fetch_widget_data for {api_url}")
    headers = {"X-Api-Key": api_key}
    results = {}

    try:
        # Step 1: Get folder list
        config_url = f"{api_url.rstrip('/')}/rest/config"
        config_resp = requests.get(config_url, headers=headers, timeout=10)
        config_resp.raise_for_status()
        folders = config_resp.json().get("folders", [])
        total_folders = len(folders)

        if "total_folders" in widget_fields:
            results["total_folders"] = total_folders

        # Step 2: Loop and collect stats
        syncing_count = 0
        total_need_bytes = 0
        total_global_bytes = 0

        for folder in folders:
            folder_id = folder.get("id")
            if not folder_id:
                continue

            status_url = f"{api_url.rstrip('/')}/rest/db/status?folder={folder_id}"
            status_resp = requests.get(status_url, headers=headers, timeout=10)
            status_resp.raise_for_status()
            status_data = status_resp.json()

            need_bytes = status_data.get("needBytes", 0)
            global_bytes = status_data.get("globalBytes", 0)

            if need_bytes > 0:
                syncing_count += 1
                total_need_bytes += need_bytes

            total_global_bytes += global_bytes

        if "folders_syncing" in widget_fields:
            results["folders_syncing"] = syncing_count
        if "remaining_mb" in widget_fields:
            results["remaining_mb"] = round(total_need_bytes / (1024 * 1024), 2)
        if "total_mb" in widget_fields:
            results["total_mb"] = round(total_global_bytes / (1024 * 1024), 2)

    except Exception as e:
        logger.error(f"❌ Error fetching Syncthing stats: {e}")
        for key in widget_fields:
            results[key] = f"error: {str(e)}"

    return results
