import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "/data/bot.db")


def run():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = [r[1] for r in c.execute("PRAGMA table_info(routes)").fetchall()]
    if "route_polyline" not in existing:
        c.execute("ALTER TABLE routes ADD COLUMN route_polyline TEXT")
        conn.commit()
        print("✅ route_polyline column added")
    else:
        print("ℹ️ route_polyline already exists, skip")
    conn.close()


if __name__ == "__main__":
    run()
