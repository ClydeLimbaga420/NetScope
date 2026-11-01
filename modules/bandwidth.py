import time
import psutil


class BandwidthMonitor:

    def __init__(self):

        self.previous = psutil.net_io_counters()
        self.previous_time = time.monotonic()

    def get_rates(self):

        current = psutil.net_io_counters()

        now = time.monotonic()

        elapsed = max(
            now - self.previous_time,
            0.001
        )

        download = max(
            current.bytes_recv - self.previous.bytes_recv,
            0
        ) / elapsed

        upload = max(
            current.bytes_sent - self.previous.bytes_sent,
            0
        ) / elapsed

        self.previous = current
        self.previous_time = now

        return {
            "download_bytes_sec": round(download, 1),

            "upload_bytes_sec": round(upload, 1),

            "download_mbps": round(
                download * 8 / 1_000_000,
                3
            ),

            "upload_mbps": round(
                upload * 8 / 1_000_000,
                3
            ),

            "total_received_bytes": current.bytes_recv,

            "total_sent_bytes": current.bytes_sent
        }