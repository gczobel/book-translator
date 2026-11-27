import os
import sys

from agentpr import review, run

# `python3 -m agentpr merge` decides the merge; `python3 -m agentpr review` is the llm-review check.
COMMANDS = {"merge": run.run, "review": review.run}

if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
    print(f"usage: python3 -m agentpr {'|'.join(COMMANDS)}")
    sys.exit(2)
sys.exit(COMMANDS[sys.argv[1]](os.environ))
