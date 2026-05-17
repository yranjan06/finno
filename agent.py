"""
Finno — finance agent. Session 1 writes memory, session 2 picks it up.
No frameworks. LLM for judgment only, math in code.
"""

import os, re, json
import tools as _tools
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from groq import Groq
from dotenv import load_dotenv
from tools import get_recent_transactions, get_account_balance, get_upcoming_bills, set_reminder

load_dotenv()
if not os.getenv("GROQ_API_KEY"):
    raise EnvironmentError("GROQ_API_KEY not set — copy .env.example to .env")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MEMORY_FILE   = "finno_memory.json"
SCENARIO_DATE = {1: "2025-11-03", 2: "2025-11-06"}
USER_PROFILE  = {
    "name": "Priya Sharma", "age": 28, "city": "Bangalore",
    "monthly_income": 120000, "goal": "Save Rs.15L in 2 years for house down payment"
}

TOOLS = [
    {"type":"function","function":{"name":"get_account_balance","description":"Get current balances. Always call for fresh data.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"get_recent_transactions","description":"Transactions for last N days. Pass category to filter e.g. food_delivery.","parameters":{"type":"object","properties":{"days":{"type":"integer","description":"Days to look back"},"category":{"type":"string","description":"Category to filter"}},"required":["days"]}}},
    {"type":"function","function":{"name":"get_upcoming_bills","description":"Upcoming bills for next 30 days.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"set_reminder","description":"Set a reminder.","parameters":{"type":"object","properties":{"date":{"type":"string","description":"YYYY-MM-DD"},"content":{"type":"string","description":"Reminder text"}},"required":["date","content"]}}}
]

# store: goals, commitments, patterns, summary
# never store: balance, bills, transactions — stale instantly

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
        with open(MEMORY_FILE) as f:
            data = json.load(f)
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        return Memory(**valid)
    except (json.JSONDecodeError, TypeError):
        print("[MEMORY] corrupted , starting fresh")
        return Memory()


def save_memory(m: Memory):
    m.last_updated = datetime.now().isoformat()
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(asdict(m), f, indent=2)
    except IOError as e:
        print(f"[MEMORY] save failed : {e}")


def execute_tool(name: str, args: dict) -> str:
    args = args or {}
    print(f"\n[TOOL] {name}({args})")

    try:
        if name == "get_account_balance":
            result = get_account_balance()

        elif name == "get_recent_transactions":
            days   = int(args.get("days", 30))
            today  = SCENARIO_DATE.get(_tools.CURRENT_SESSION, "2025-11-03")
            cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
            txns   = [t for t in get_recent_transactions(days) if t["date"] > cutoff]
            cat    = args.get("category", "").strip().lower()

            if cat and cat not in ("all", "any", "none"):
                filtered = [t for t in txns if t["category"] == cat]
                result   = {
                    "category":          cat,
                    "total_spent":       sum(abs(t["amount"]) for t in filtered),
                    "transaction_count": len(filtered)
                }
            else:
                bd = {}
                for t in txns:
                    if t["amount"] < 0:
                        bd[t["category"]] = bd.get(t["category"], 0) + abs(t["amount"])
                result = {"breakdown_by_category": bd, "total_debits": sum(bd.values())}

        elif name == "get_upcoming_bills":
            result = get_upcoming_bills(30)

        elif name == "set_reminder":
            date, content = args.get("date","").strip(), args.get("content","").strip()
            if not date or not content:
                print(f"[TOOL] set_reminder missing {'date' if not date else 'content'}")
                result = {"error": "date and content are required"}
            else:
                result = set_reminder(date, content)

        else:
            result = {"error": f"unknown tool: {name}"}

    except Exception as e:
        print(f"[TOOL] {name} crashed : {e}")
        result = {"error": str(e)}

    print(f"[TOOL] result: {json.dumps(result, indent=2)}")
    return json.dumps(result)


def build_prompt(memory: Memory, session_num: int) -> str:
    today = SCENARIO_DATE.get(session_num, "2025-11-03")
    p = f"""You are Priya's personal finance agent.
Today: {today} | {USER_PROFILE['name']}, {USER_PROFILE['age']}, {USER_PROFILE['city']}, Rs.{USER_PROFILE['monthly_income']}/month
Goal: {USER_PROFILE['goal']}

Rules:
- balance/bills/transactions -> ALWAYS call tool first, never quote memory numbers
- spending questions -> call get_recent_transactions with specific category
- do NOT show arithmetic , just state final number
- financial decision -> check commitments first
- call set_reminder when asked OR when request conflicts with commitment
- reminder dates must be November 2025
- tone: brief, direct, friendly"""

    if memory.summary:
        p += f"""

Last session:
{memory.summary}
Commitments: {memory.commitments}
Goals: {memory.goals}
Patterns: {memory.observed_patterns}

These numbers are stale — fetch fresh via tools.
If request conflicts with commitment , call set_reminder first."""
    return p


def build_transcript(messages: list) -> str:
    return "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str) and m["content"].strip()
    )


def sync_memory(existing: Memory, messages: list) -> Memory:
    has            = bool(existing.summary)
    existing_block = f"Existing memory:\n{json.dumps(asdict(existing), indent=2)}\n\n" if has else ""
    action         = "merge new observations in, do not drop existing commitments" if has else "extract key information"

    prompt = f"""Finance conversation — {action}.
Return ONLY valid JSON, no markdown.

{existing_block}Conversation:
{build_transcript(messages)}

Return:
{{"summary":"2-3 lines on key decisions","goals":[{{"goal_id":"g1","description":"...","target_amount":1500000,"status":"active"}}],"commitments":[{{"commitment_id":"c1","action_item":"...","frequency":"one-time","due_date":"..."}}],"observed_patterns":[{{"category":"...","observation":"...","confidence_score":"high"}}]}}

House down payment target_amount is always 1500000."""

    try:
        raw = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        ).choices[0].message.content.strip()
    except Exception as e:
        print(f"[MEMORY] sync failed : {e}")
        return existing

    raw = re.sub(r"```[\w]*\n?|```", "", raw).strip()

    try:
        data  = json.loads(raw)
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        mem   = Memory(**valid)
        print(f"\n[MEMORY] Synced:\n{json.dumps(data, indent=2)}")
        return mem
    except (json.JSONDecodeError, TypeError) as e:
        print(f"[MEMORY] bad JSON : {e}")
        return existing


def agent_turn(messages: list) -> list:
    try:
        response = client.chat.completions.create(
            model=MODEL, messages=messages,
            tools=TOOLS, tool_choice="auto"
        )
    except Exception as e:
        print(f"[FINNO] LLM failed : {e}")
        messages.append({"role": "assistant", "content": "Something went wrong, please try again."})
        return messages

    iteration, MAX_ITER = 0, 10

    while response.choices[0].finish_reason == "tool_calls":
        iteration += 1
        if iteration > MAX_ITER:
            print(f"[FINNO] hit max iterations , breaking")
            messages.append({"role": "assistant", "content": "Got stuck, please try again."})
            return messages

        msg = response.choices[0].message
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in msg.tool_calls
            ]
        })

        tool_results = []
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                print(f"[TOOL] bad args : {tc.function.arguments}")
                args = {}
            tool_results.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      execute_tool(tc.function.name, args)
            })

        messages.extend(tool_results)

        try:
            response = client.chat.completions.create(
                model=MODEL, messages=messages,
                tools=TOOLS, tool_choice="auto"
            )
        except Exception as e:
            print(f"[FINNO] LLM failed after tools : {e}")
            messages.append({"role": "assistant", "content": "Something went wrong, please try again."})
            return messages

    final = response.choices[0].message.content
    messages.append({"role": "assistant", "content": final})
    print(f"\n[FINNO] {final}")
    return messages


def run_session(session_num: int):
    print(f"\n{'='*50}\nFINNO — Session {session_num}\n{'='*50}\n")
    memory = load_memory()
    print(f"[MEMORY] Loaded: {memory.summary or 'none'}")

    active   = memory if memory.summary else Memory()
    messages = [{"role": "system", "content": build_prompt(active, session_num)}]

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": user_input})
        messages = agent_turn(messages)

    memory = sync_memory(memory, messages)
    save_memory(memory)
    print("\n[MEMORY] Saved.")


if __name__ == "__main__":
    import sys
    run_session(int(sys.argv[1]) if len(sys.argv) > 1 else 1)