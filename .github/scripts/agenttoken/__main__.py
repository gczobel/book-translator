import os
import sys

from agenttoken.run import run

sys.exit(run(os.environ, sys.stdout, sys.stderr))
