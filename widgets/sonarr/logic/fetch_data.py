import requests

def fetch_widget_data(api_url, api_key, widget_fields):
    """
    Fetch data from the given API URL with the provided API key,
    and return the requested fields in a key-value format.
    """
    # Make the API request
    response = requests.get(api_url, params={"apikey": api_key})

    if response.status_code == 200:
        data = response.json()

        # Prepare the field-value dictionary to return
        widget_data = {}

        # Process and fetch the requested fields
        for field in widget_fields:
            if field in data:
                widget_data[field] = data[field]
            else:
                widget_data[field] = None  # If the field is not found, set as None

        return widget_data
    else:
        # If the API call failed, return an error
        return {"error": f"Failed to fetch data from API. Status code: {response.status_code}"}
