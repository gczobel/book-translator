import os
import sys

from repair.run import build, names, push, select

STEPS = {"select": select, "build": build, "names": names, "push": push}

if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
    print(f"usage: python3 -m repair {'|'.join(STEPS)}")
    sys.exit(2)
sys.exit(STEPS[sys.argv[1]](os.environ))
