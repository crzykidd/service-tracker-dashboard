import sys
import json
import os
import logging
from importlib import import_module

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)

def load_settings(widget_module):
    settings_path = os.path.join("widgets", widget_module, "settings.json")
    if not os.path.exists(settings_path):
        print(f"❌ settings.json not found for widget '{widget_module}' at {settings_path}")
        sys.exit(1)

    with open(settings_path, "r") as f:
        return json.load(f)

def main():
    if len(sys.argv) < 5:
        print("Usage:\n  python test-widget.py <widget_module> <url> <api_key> <field1> [<field2> ...]")
        sys.exit(1)

    widget_module = sys.argv[1]
    base_url = sys.argv[2]
    api_key = sys.argv[3]
    requested_fields = sys.argv[4:]

    print(f"🧪 Testing widget: {widget_module}")
    print(f"🔗 URL: {base_url}")
    print(f"📦 Fields: {requested_fields}")

    settings = load_settings(widget_module)
    available_fields = settings.get("available_fields", [])

    try:
        module = import_module(f"widgets.{widget_module}.fetch_data")
        fetch_func = getattr(module, "fetch_widget_data")
    except Exception as e:
        print(f"❌ Failed to import widget fetcher: {e}")
        sys.exit(1)

    data = fetch_func(base_url, api_key, requested_fields, available_fields)

    print("📊 Results:")
    for key, value in data.items():
        print(f"🔹 {key}: {value}")

if __name__ == "__main__":
    main()
