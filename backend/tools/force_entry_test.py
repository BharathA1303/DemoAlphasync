import httpx
import sys

url = "http://127.0.0.1:8000/api/zeroloss/debug/force_entry"
payload = {"symbol": "RELIANCE", "force": True, "quantity": 1}

try:
    r = httpx.post(url, json=payload, timeout=10.0)
    print(r.status_code)
    print(r.text)
except Exception as e:
    print("ERROR", e)
    sys.exit(1)
