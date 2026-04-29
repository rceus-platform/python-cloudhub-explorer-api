"""Database Cleanup Script.

This script resets the SQLite database journaling mode and removes
leftover WAL/SHM artifacts to ensure system stability on resource-constrained environments.
"""

import os
import sqlite3

# The database file used by the application
db_file = "cloudhub.db"
shm_file = "cloudhub.db-shm"
wal_file = "cloudhub.db-wal"


def cleanup():
    """Reset database to standard journaling mode and remove temporary WAL files."""

    if not os.path.exists(db_file):
        print(f"❌ Database file {db_file} not found in current directory.")
        return

    print(f"🛠️ Resetting {db_file} to standard journaling mode...")
    try:
        # Connecting and setting journal_mode=DELETE explicitly resets the DB header
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=DELETE;")
        conn.close()
        print("✅ Database mode reset successfully.")
    except Exception as e:
        print(f"❌ Error resetting database: {e}")

    # Remove the leftover WAL files
    for f in [shm_file, wal_file]:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"✅ Removed leftover file: {f}")
            except Exception as e:
                print(f"❌ Error removing {f}: {e}")
        else:
            print(f"ℹ️ {f} not found (already gone).")


if __name__ == "__main__":
    cleanup()
