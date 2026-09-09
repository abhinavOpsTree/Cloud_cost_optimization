import requests
import json

try:
    r = requests.post("http://localhost:8001/api/ingest?days=7")
    data = r.json()
    if "traceback" in data:
        print(data["traceback"])
    else:
        print("No traceback found. Response:", data)
except Exception as e:
    print("Request failed:", e)
