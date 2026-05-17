"""
test.py - runs exact sessions.md messages automatically
agent.py has input() loop for real use , this file is for assignment testing
"""

import sys
from unittest.mock import patch
import tools
from agent import run_session

SESSION_1_TURNS = [
    "I just got my salary credited. Help me figure out how much I can realistically save this month.",
    "I feel like I'm spending too much on food delivery. How much did I actually spend on it last month?",
    "Okay that's worse than I thought. Let's say I want to cut that in half AND put aside ₹30,000 for my house fund this month — is that realistic given my upcoming bills?",
    "Got it. Remind me to actually transfer the ₹30,000 to my house fund on the 25th.",
]

SESSION_2_TURNS = [
    "Hey, my colleague is selling his MacBook for ₹80,000, barely used. I've been wanting to upgrade. Should I buy it?",
]

if __name__ == "__main__":
    session = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    turns   = SESSION_1_TURNS if session == 1 else SESSION_2_TURNS

    # auto flip session — no need to touch tools.py manually
    tools.CURRENT_SESSION = session
    print(f"[TEST] CURRENT_SESSION set to {session}")

    with patch("builtins.input", side_effect=turns + ["exit"]):
        run_session(session)