import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "netscope.db"


def get_connection():

    connection = sqlite3.connect(DATABASE_PATH)

    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():

    with get_connection() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS network_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,

                download_mbps REAL,

                upload_mbps REAL,

                latency_ms REAL,

                internet_status INTEGER

            )
        """)

        connection.commit()


def save_network_history(
    download_mbps,
    upload_mbps,
    latency_ms,
    internet_status
):

    with get_connection() as connection:

        connection.execute(
            """
            INSERT INTO network_history (
                download_mbps,
                upload_mbps,
                latency_ms,
                internet_status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                download_mbps,
                upload_mbps,
                latency_ms,
                int(internet_status)
            )
        )

        connection.commit()