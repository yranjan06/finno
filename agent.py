"""
Finno - personal finance agent
"""

import os
import json
import tools as _tools
from datetime import datetime
from dataclasses import dataclass, field, asdict
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MEMORY_FILE = "finno_memory.json"

USER_PROFILE = {
    "name": "Priya Sharma",
    "age": 28,
    "city": "Bangalore",
    "monthly_income": 120000,
    "goal": "Save Rs.15L in 2 years for house down payment"
}

# hardcoding scenario dates because datetime.now() gives wrong year since this runs in 2025
SCENARIO_DATE = {1: "2025-11-03", 2: "2025-11-06"}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_account_balance",
            "description": "Get current account balances. Always call for fresh data.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_transactions",
            "description": "Get transactions for last N days. Pass category to filter spending for one category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days to look back"},
                    "category": {"type": "string", "description": "Category to filter e.g. food_delivery, rent, shopping"}
                },
                "required": ["days"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_bills",
            "description": "Get upcoming bills for next 30 days.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Set a reminder for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date":    {"type": "string", "description": "Date YYYY-MM-DD"},
                    "content": {"type": "string", "description": "Reminder text"}
                },
                "required": ["date", "content"]
            }
        }
    }
]

# what we store vs what we always fetch fresh
# storing: goals, commitments, patterns, summary
# never storing: balance, bills, transactions - those go stale

@dataclass
class Memory:
    summary:           str  = ""
    goals:             list = field(default_factory=list)
    commitments:       list = field(default_factory=list)
    observed_patterns: list = field(default_factory=list)
    last_updated:      str  = ""

def load_memory() -> Memory:
    if not os.path.exists(MEMORY_FILE):
        return Memory()
    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
        # filter unknown keys so old finno_memory.json files dont crash us
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        return Memory(**valid)
    except (json.JSONDecodeError, TypeError):
        print("[MEMORY] corrupted memory file , starting fresh")
        return Memory()


def save_memory(m: Memory):
    m.last_updated = datetime.now().isoformat()
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(asdict(m), f, indent=2)
    except IOError as e:
        print(f"[MEMORY] failed to save : {e}")

# TODO: memory layer next
# TODO: prompt builder next
# TODO: tool executor next
# TODO: agent loop next

def run_session(session_num: int):
    print(f"\n{'='*50}\nFINNO - Session {session_num}\n{'='*50}\n")
    # TODO: build this out properly


if __name__ == "__main__":
    import sys
    run_session(int(sys.argv[1]) if len(sys.argv) > 1 else 1)