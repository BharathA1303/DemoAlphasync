import asyncio
import httpx
from datetime import datetime, timedelta, timezone

API_BASE = "http://147.93.168.157:8003"
CLIENT_ID = "c_bfe821a0d3b6920f"
CLIENT_SECRET = "s_9ad30e8c71df542b6a9c1e0e8f8139be"

async def test_date(client, token, date_str):
    headers = {"Authorization": f"Bearer {token}"}
    print(f"\n--- Testing date {date_str} ---")
    
    # Test session creation
    session_id = None
    try:
        resp = await client.post(
            f"{API_BASE}/v1/sessions",
            headers=headers,
            json={"date": date_str, "replay_speed": 1}
        )
        print(f"Session creation status: {resp.status_code}")
        if resp.status_code in (200, 201):
            session_id = resp.json()["session_id"]
            print(f"Created session {session_id}")
        else:
            print("Response:", resp.text)
    except Exception as e:
        print(f"Session creation failed: {e}")

    # Test start session clock if created
    if session_id:
        try:
            resp = await client.post(
                f"{API_BASE}/v1/sessions/{session_id}/start",
                headers=headers
            )
            print(f"Session start status: {resp.status_code}")
            if resp.status_code not in (200, 201, 204):
                print("Response:", resp.text)
        except Exception as e:
            print(f"Session start failed: {e}")

async def main():
    async with httpx.AsyncClient() as client:
        # Authenticate
        print("Authenticating...")
        resp = await client.post(
            f"{API_BASE}/v1/auth/token",
            json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
        )
        if resp.status_code != 200:
            print("Authentication failed:", resp.text)
            return
        token = resp.json()["access_token"]
        print("Authenticated successfully.")

        # Test various dates relative to today (2026-07-06)
        today = datetime.now(timezone.utc).date()
        for i in range(1, 10):
            test_dt = today - timedelta(days=i)
            await test_date(client, token, test_dt.isoformat())

if __name__ == "__main__":
    asyncio.run(main())
