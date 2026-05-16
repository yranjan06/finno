"""
Finno - personal finance agent
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
MEMORY_FILE = "finno_memory.json"

USER_PROFILE = {
    "name": "Priya Sharma",
    "age": 28,
    "city": "Bangalore",
    "monthly_income": 120000,
    "goal": "Save Rs.15L in 2 years for house down payment"
}


def run_session(session_num: int):
    print(f"Finno - Session {session_num}")
    # TODO: build this out


if __name__ == "__main__":
    import sys
    run_session(int(sys.argv[1]) if len(sys.argv) > 1 else 1)