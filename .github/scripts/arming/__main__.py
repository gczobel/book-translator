import os
import sys

from arming.run import arm, select

STEPS = {"select": select, "arm": arm}

if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
    print("usage: python3 -m arming select|arm")
    sys.exit(2)
sys.exit(STEPS[sys.argv[1]](os.environ))
