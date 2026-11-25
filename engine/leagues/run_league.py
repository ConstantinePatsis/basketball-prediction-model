import importlib
import sys

from common import run

mod = importlib.import_module(sys.argv[1])
start = int(sys.argv[2]) if len(sys.argv) > 2 else 2016
end = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
workers = int(sys.argv[4]) if len(sys.argv) > 4 else 6
run(mod, range(start, end + 1), workers=workers, log=lambda m: print(m, flush=True))
print("DONE", flush=True)
