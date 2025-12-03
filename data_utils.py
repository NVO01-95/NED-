import json
import os

DATA_FILE = os.path.join("data", "ned_data.json")

def load_data():
    """Read data from ned_data.json and return it as a Python dict."""
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_data(data):
    """Write the provided Python dict to ned_data.json."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
