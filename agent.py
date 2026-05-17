"""
Finno - personal finance agent
"""

import os
import json
import tools as _tools
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from groq import Groq
from dotenv import load_dotenv
from tools import get_recent_transactions, get_account_balance, get_upcoming_bills, set_reminder
import re

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MEMORY_FILE = "finno_memory.json"

if not os.getenv("GROQ_API_KEY"):
    raise EnvironmentError("[FINNO] GROQ_API_KEY not set , copy .env.example to .env and add your key")

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
        days = int(args.get("days", 30))
        txns = get_recent_transactions(days)

        today = SCENARIO_DATE.get(_tools.CURRENT_SESSION, "2025-11-03")
        cutoff = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)
        ).strftime("%Y-%m-%d")

        txns = [t for t in txns if t["date"] > cutoff]

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
        date = args.get("date", "").strip()
        content = args.get("content", "").strip()

        # LLM sometimes forgets required params , guard both
        if not date:
            print("[TOOL] set_reminder called without date , skipping")
            result = {"error": "date is required but was not provided"}
        elif not content:
            print("[TOOL] set_reminder called without content , skipping")
            result = {"error": "content is required but was not provided"}
        else:
            result = set_reminder(date, content)

    else:
        result = {"error": f"unknown tool: {name}"}

    print(f"[RESULT] {json.dumps(result, indent=2)}")
    return json.dumps(result)

def build_prompt(memory: Memory, session_num: int) -> str:
    today = SCENARIO_DATE.get(session_num, "2025-11-03")

    base = f"""You are Priya's personal finance agent.
Today's date: {today}
User: {USER_PROFILE['name']}, {USER_PROFILE['age']}, {USER_PROFILE['city']}, Rs.{USER_PROFILE['monthly_income']}/month
Goal: {USER_PROFILE['goal']}

Rules:
- Balance / bills / transactions -> ALWAYS call the tool first, never quote memory numbers
- For spending questions call get_recent_transactions with specific category
- Do NOT show arithmetic steps in your response , just state the final number
- Financial decision detected -> check active commitments first then respond
- Call set_reminder when user asks to be reminded OR when request conflicts with a saved commitment
- All reminder dates must be in November 2025 (today is {today})
- Tone: brief, direct, friendly"""

    if memory.summary:
        base += f"""

What I remember from last session:
{memory.summary}
Commitments: {memory.commitments}
Goals: {memory.goals}
Patterns: {memory.observed_patterns}

Numbers above are stale - always fetch fresh via tools.
If the user request conflicts with a commitment you MUST call set_reminder before responding."""

    return base


def agent_turn(messages: list) -> list:
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto"
        )
    except Exception as e:
        print(f"[FINNO] LLM call failed : {e}")
        messages.append({"role": "assistant", "content": "Sorry, something went wrong. Please try again."})
        return messages

    iteration = 0
    MAX_ITERATIONS = 10

    while response.choices[0].finish_reason == "tool_calls":

        iteration += 1
        if iteration > MAX_ITERATIONS:
            print(f"[FINNO] hit max tool iterations ({MAX_ITERATIONS}) , breaking out")
            messages.append({"role": "assistant", "content": "Sorry, I got stuck in a loop. Please try again."})
            return messages

        msg = response.choices[0].message

        # normalize fully to dict , no SDK objects in messages list
        tool_calls_dict = []
        for tc in msg.tool_calls:
            tool_calls_dict.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": tool_calls_dict
        })

        tool_results = []
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                print(f"[TOOL] bad arguments from LLM : {tc.function.arguments}")
                args = {}
            result = execute_tool(tc.function.name, args)
            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })

        messages.extend(tool_results)

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto"
            )
        except Exception as e:
            print(f"[FINNO] LLM call failed after tool results : {e}")
            messages.append({"role": "assistant", "content": "Sorry, something went wrong. Please try again."})
            return messages

    final = response.choices[0].message.content
    messages.append({"role": "assistant", "content": final})
    print(f"\n[FINNO] {final}")
    return messages


def extract_memory(messages: list) -> Memory:
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m.get("content").strip()
    )

    prompt = f"""Extract key information from this finance conversation.
Return ONLY valid JSON - no markdown, no explanation, no extra text.

Conversation:
{transcript}

Return exactly this structure:
{{
  "summary": "2-3 lines covering key decisions and commitments made",
  "goals": [{{"goal_id": "g1", "description": "...", "target_amount": 1500000, "status": "active"}}],
  "commitments": [{{"commitment_id": "c1", "action_item": "...", "frequency": "one-time", "due_date": "..."}}],
  "observed_patterns": [{{"category": "...", "observation": "...", "confidence_score": "high"}}]
}}

Note: target_amount for house down payment is always 1500000 (Rs.15 lakh)."""

    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        ).choices[0].message.content.strip()
    except Exception as e:
        print(f"[MEMORY] extract_memory LLM call failed : {e}")
        return Memory()

    # strip markdown fences if model adds them anyway
    # handles ```json , ```JSON , ``` , ~ fences etc
    raw = re.sub(r"```[\w]*\n?", "", raw).strip()
    raw = re.sub(r"```", "", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[MEMORY] still bad JSON after cleaning : {e}")
        print(f"[MEMORY] raw output was : {raw[:200]}")
        return Memory()

    # guard against LLM returning unexpected keys
    try:
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        memory = Memory(**valid)
    except (TypeError, AttributeError) as e:
        print(f"[MEMORY] memory construction failed : {e}")
        return Memory()

    print(f"\n[MEMORY] Extracted:\n{json.dumps(data, indent=2)}")
    return memory

def update_memory(existing: Memory, messages: list) -> Memory:
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in messages
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m.get("content").strip()
    )

    prompt = f"""Given this existing memory and a new conversation, update the memory with any new observations or decisions.
Return ONLY valid JSON - no markdown, no explanation.

Existing memory:
{json.dumps(asdict(existing), indent=2)}

New conversation:
{transcript}

Return exactly this structure with updates merged in:
{{
  "summary": "updated 2-3 lines covering all sessions so far",
  "goals": [{{"goal_id": "g1", "description": "...", "target_amount": 1500000, "status": "active"}}],
  "commitments": [{{"commitment_id": "c1", "action_item": "...", "frequency": "one-time", "due_date": "..."}}],
  "observed_patterns": [{{"category": "...", "observation": "...", "confidence_score": "high"}}]
}}

Only add genuinely new information. Do not drop existing commitments or goals."""

    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        ).choices[0].message.content.strip()
    except Exception as e:
        print(f"[MEMORY] update_memory LLM call failed : {e}")
        return existing

    raw = re.sub(r"```[\w]*\n?", "", raw).strip()
    raw = re.sub(r"```", "", raw).strip()

    try:
        data = json.loads(raw)
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        updated = Memory(**valid)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"[MEMORY] update failed , keeping existing : {e}")
        return existing

    print(f"\n[MEMORY] Updated:\n{json.dumps(data, indent=2)}")
    return updated

def run_session(session_num: int):
    print(f"\n{'='*50}\nFINNO - Session {session_num}\n{'='*50}\n")

    memory = load_memory()
    print(f"[MEMORY] Loaded: summary={memory.summary or 'none'}")

    messages = [{"role": "system", "content": build_prompt(memory, session_num)}]

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": user_input})
        messages = agent_turn(messages)

    if session_num == 1:
        memory = extract_memory(messages)
        save_memory(memory)
        print("\n[MEMORY] Saved to disk.")

    elif session_num == 2:
        memory = update_memory(memory, messages)
        save_memory(memory)
        print("\n[MEMORY] Updated and saved to disk.")


def build_messages(memory: Memory, session_num: int) -> list:
    return [{"role": "system", "content": build_prompt(memory, session_num)}]


def run_session(session_num: int):
    print(f"\n{'='*50}\nFINNO - Session {session_num}\n{'='*50}\n")

    memory = load_memory()
    print(f"[MEMORY] Loaded: summary={memory.summary or 'none'}")

    # only inject memory if something was actually saved before
    active_memory = memory if memory.summary else Memory()
    messages = build_messages(active_memory, session_num)

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": user_input})
        messages = agent_turn(messages)

    if session_num == 1:
        memory = extract_memory(messages)
        save_memory(memory)
        print("\n[MEMORY] Saved to disk.")

    elif session_num == 2:
        memory = update_memory(memory, messages)
        save_memory(memory)
        print("\n[MEMORY] Updated and saved to disk.")

if __name__ == "__main__":
    import sys
    run_session(int(sys.argv[1]) if len(sys.argv) > 1 else 1)