import sys
import time


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

    def issaty(self):
        return False

log_file = open(
    f"close_iframe{time.time.strftime('%d', time.localtime())}.log", 
    "a", 
    encoding="utf-8", 
    buffering=1
)

original_stdout = sys.stdout
sys.stdout = Tee(sys.stdout, log_file)
