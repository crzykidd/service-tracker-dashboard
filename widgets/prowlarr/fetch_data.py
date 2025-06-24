import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def fetch_widget_data(api_url, api_key, widget_fields, available_fields):
    logger.info(f"📢 Entered fetch_widget_data for {api_url}")
    headers = {"X-Api-Key": api_key}
    results = {}

    try:
        # Build the 7-day start date
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        start_date = seven_days_ago.isoformat() + "Z"
        base_url = api_url.rstrip('/')
        stats_url = f"{base_url}/api/v1/indexerstats"
        full_url = f"{stats_url}?startDate={start_date}"

        response = requests.get(full_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        indexers = data.get("indexers", [])

        # All-time and 7-day keys
        total_grabs = sum(i.get("numberOfGrabs", 0) for i in indexers)
        total_failures = sum(i.get("numberOfFailedGrabs", 0) for i in indexers)
        total_queries = sum(i.get("numberOfQueries", 0) for i in indexers)
        total_failed_queries = sum(i.get("numberOfFailedQueries", 0) for i in indexers)

        if "total_grabs" in widget_fields:
            results["total_grabs"] = total_grabs
        if "total_failures" in widget_fields:
            results["total_failures"] = total_failures
        if "total_queries" in widget_fields:
            results["total_queries"] = total_queries
        if "total_failed_queries" in widget_fields:
            results["total_failed_queries"] = total_failed_queries

        if "recent_grabs_7d" in widget_fields:
            results["recent_grabs_7d"] = total_grabs
        if "recent_failures_7d" in widget_fields:
            results["recent_failures_7d"] = total_failures
        if "recent_queries_7d" in widget_fields:
            results["recent_queries_7d"] = total_queries
        if "recent_failed_queries_7d" in widget_fields:
            results["recent_failed_queries_7d"] = total_failed_queries

        logger.debug(f"✅ 7-day Prowlarr results: {results}")

    except Exception as e:
        logger.error(f"❌ Error fetching Prowlarr widget data: {e}")
        for key in widget_fields:
            results[key] = f"error: {str(e)}"

    return results
