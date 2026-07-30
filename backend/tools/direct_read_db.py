import sqlite3
import base64

db_path = "C:/Users/megan/OneDrive/Desktop/all files for vmax/simulation/alphasync.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("SELECT api_key, api_secret, base_url, is_enabled, connection_status, error_message FROM data_feed_configs ORDER BY updated_at DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        api_key, api_secret, base_url, is_enabled, connection_status, error_message = row
        print("API Key (Client ID):", api_key)
        print("API Secret (Raw):", api_secret)
        print("Base URL:", base_url)
        print("Is Enabled:", is_enabled)
        print("Connection Status:", connection_status)
        print("Error Message:", error_message)
    else:
        print("No configs found in data_feed_configs")
except Exception as e:
    print("Error querying db:", e)
finally:
    conn.close()
