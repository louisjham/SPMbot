"""
Pytest configuration for Kali Agent tests.

Sets up the Python path so that imports work correctly.
"""

import sys
from pathlib import Path

# Add the kali-agent directory to the Python path
# This allows imports like `from skills.base import ...` to work
kali_agent_dir = Path(__file__).parent.parent
if str(kali_agent_dir) not in sys.path:
    sys.path.insert(0, str(kali_agent_dir))
