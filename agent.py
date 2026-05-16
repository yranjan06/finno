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
from tools import get_recent_transactions, get_account_balance, get_upcoming_bills, set_reminder

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

def execute_tool(name: str, args: dict) -> str:
    args = args or {}
    print(f"\n[TOOL] {name}({args})")

    if name == "get_account_balance":
        result = get_account_balance()

    elif name == "get_recent_transactions":
        txns = get_recent_transactions(int(args.get("days", 30)))
        category = args.get("category", "").strip().lower()

        if category and category not in ("all", "any", "none"):
            filtered = [t for t in txns if t["category"] == category]
            total = sum(abs(t["amount"]) for t in filtered)
            result = {
                "category": category,
                "total_spent": total,
                "transaction_count": len(filtered)
            }
        else:
            breakdown = {}
            for t in txns:
                if t["amount"] < 0:
                    cat = t["category"]
                    breakdown[cat] = breakdown.get(cat, 0) + abs(t["amount"])
            result = {
                "breakdown_by_category": breakdown,
                "total_debits": sum(breakdown.values())
            }

    elif name == "get_upcoming_bills":
        result = get_upcoming_bills(30)

    elif name == "set_reminder":
        result = set_reminder(
            args.get("date", ""),
            args.get("content", "")
        )

    else:
        result = {"error": f"unknown tool: {name}"}

    print(f"[RESULT] {json.dumps(result, indent=2)}")
    return json.dumps(result)

def agent_turn(messages: list) -> list:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOL_DEFINITIONS,
        tool_choice="auto"
    )

    iteration = 0
    # TODO: add max iteration guard later

    while response.choices[0].finish_reason == "tool_calls":
        msg = response.choices[0].message
        # normalize to dict so messages list stays consistent
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in msg.tool_calls
            ]
        })

        tool_results = []
        for tc in msg.tool_calls:
            result = execute_tool(
                tc.function.name,
                json.loads(tc.function.arguments)
            )
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })

        messages.extend(tool_results)
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto"
        )

    final = response.choices[0].message.content
    messages.append({"role": "assistant", "content": final})
    print(f"\n[FINNO] {final}")
    return messages


def run_session(session_num: int):
    print(f"\n{'='*50}\nFINNO - Session {session_num}\n{'='*50}\n")

    memory = load_memory()
    print(f"[MEMORY] Loaded: summary={memory.summary or 'none'}")

    messages = [{"role": "system", "content": f"You are Priya's personal finance agent. Today is {SCENARIO_DATE.get(session_num)}"}]

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": user_input})
        messages = agent_turn(messages)


if __name__ == "__main__":
    import sys
    run_session(int(sys.argv[1]) if len(sys.argv) > 1 else 1)