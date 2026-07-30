import sqlite3

db_path = "C:/Users/megan/OneDrive/Desktop/all files for vmax/Alphasync-demo - Copy (2)/backend/alphasync.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables:", [t[0] for t in cursor.fetchall()])
    cursor.execute("SELECT api_key, api_secret, base_url, is_enabled, connection_status, error_message FROM data_feed_configs ORDER BY updated_at DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        print("Config:", row)
    else:
        print("No configs")
except Exception as e:
    print("Error:", e)
finally:
    conn.close()
