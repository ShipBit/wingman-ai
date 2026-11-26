"""Entry point of WingmanAiInput.exe (Windows only).

The program Core starts to press keys in a game that runs as administrator.
See services/elevated_input.py. It is built without Core's modules on purpose:
it holds a right Core does not have and should be able to do nothing else.
"""

import sys

from services.elevated_input import run_helper

if __name__ == "__main__":
    sys.exit(run_helper(sys.argv[1:]))
