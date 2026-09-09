import requests
import time

for i in range(10):
    print(f"Attempt {i+1}...")
    r = requests.post("http://localhost:8001/api/ingest?days=7")
    if r.status_code == 500:
        data = r.json()
        print("TRACEBACK:")
        print(data.get("traceback", "No traceback found"))
        break
    else:
        print("Success, retrying...")
    time.sleep(1)
