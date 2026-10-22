import sys
import time
import os

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()

    def isatty(self):
        return False

os.makedirs("intersential_logs", exist_ok=True)

log_file = open(
    os.path.join(
        "intersential_logs",
        f"close_iframe{time.strftime('%d', time.localtime())}.log"
    ),
    "a",
    encoding="utf-8",
    buffering=1
)

original_stdout = sys.stdout
sys.stdout = Tee(sys.stdout, log_file)
