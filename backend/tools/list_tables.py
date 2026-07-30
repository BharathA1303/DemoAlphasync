import sqlite3

db_path = "C:/Users/megan/OneDrive/Desktop/all files for vmax/simulation/alphasync.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print("Tables:", [t[0] for t in tables])
except Exception as e:
    print("Error querying db:", e)
finally:
    conn.close()
