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
MODEL         = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MEMORY_FILE   = "finno_memory.json"
SCENARIO_DATE = {1: "2025-11-03", 2: "2025-11-06"}
USER_PROFILE  = {"name": "Priya Sharma", "age": 28, "city": "Bangalore",
                 "monthly_income": 120000, "goal": "Save Rs.15L in 2 years for house down payment"}

TOOL_DEFS = [
    {"type":"function","function":{"name":"get_account_balance","description":"Current balances. Always call for fresh data.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"get_recent_transactions","description":"Transactions last N days. days MUST be integer e.g. 30 not '30'.","parameters":{"type":"object","properties":{"days":{"type":"integer","description":"Days to look back, integer only"},"category":{"type":"string","description":"Category filter e.g. food_delivery"}},"required":["days"]}}},
    {"type":"function","function":{"name":"get_upcoming_bills","description":"Bills due in next 30 days.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"set_reminder","description":"Set a reminder.","parameters":{"type":"object","properties":{"date":{"type":"string","description":"YYYY-MM-DD"},"content":{"type":"string"}},"required":["date","content"]}}}
]

# Memory: store goals, commitments, patterns — never balances/bills/transactions (stale)
@dataclass
class Memory:
    summary:           str  = ""
    goals:             list = field(default_factory=list)
    commitments:       list = field(default_factory=list)
    observed_patterns: list = field(default_factory=list)
    last_updated:      str  = ""

def load_memory() -> Memory:
    if not os.path.exists(MEMORY_FILE): return Memory()
    try:
        data  = json.load(open(MEMORY_FILE))
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        return Memory(**valid)
    except (json.JSONDecodeError, TypeError):
        print("[MEMORY] corrupted, starting fresh"); return Memory()

def save_memory(m: Memory):
    m.last_updated = datetime.now().isoformat()
    try: json.dump(asdict(m), open(MEMORY_FILE, "w"), indent=2)
    except IOError as e: print(f"[MEMORY] save failed: {e}")

def safe_args(name: str, args: dict) -> dict:
    if name == "get_recent_transactions" and "days" in args:
        try: args["days"] = int(args["days"])
        except (ValueError, TypeError): args["days"] = 30
    return args

def execute_tool(name: str, args: dict) -> str:
    args = safe_args(name, args or {})
    print(f"\n[TOOL] {name}({args})")
    try:
        if name == "get_account_balance":
            result = get_account_balance()
        elif name == "get_recent_transactions":
            days   = args.get("days", 30)
            today  = SCENARIO_DATE.get(_tools.CURRENT_SESSION, "2025-11-03")
            cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
            txns   = [t for t in get_recent_transactions(days) if t["date"] > cutoff]
            cat    = args.get("category", "").strip().lower()
            if cat and cat not in ("all", "any", "none"):
                filtered = [t for t in txns if t["category"] == cat]
                result   = {"category": cat, "total_spent": sum(abs(t["amount"]) for t in filtered), "transaction_count": len(filtered)}
            else:
                bd = {}
                for t in txns:
                    if t["amount"] < 0: bd[t["category"]] = bd.get(t["category"], 0) + abs(t["amount"])
                result = {"breakdown_by_category": bd, "total_debits": sum(bd.values())}
        elif name == "get_upcoming_bills":
            result = get_upcoming_bills(30)
        elif name == "set_reminder":
            date, content = args.get("date","").strip(), args.get("content","").strip()
            result = set_reminder(date, content) if date and content else {"error": "date and content required"}
        else:
            result = {"error": f"unknown tool: {name}"}
    except Exception as e:
        print(f"[TOOL] crashed: {e}"); result = {"error": str(e)}
    print(f"[TOOL] result: {json.dumps(result, indent=2)}")
    return json.dumps(result)

def build_prompt(memory: Memory, session_num: int) -> str:
    today = SCENARIO_DATE.get(session_num, "2025-11-03")
    p = f"""You are Priya's personal finance agent.
Today: {today} | {USER_PROFILE['name']}, {USER_PROFILE['age']}, {USER_PROFILE['city']}, Rs.{USER_PROFILE['monthly_income']}/month
Goal: {USER_PROFILE['goal']}

Rules:
- balance/bills/transactions -> ALWAYS call tool first, never use memory numbers
- quote balances as EXACT numbers from tool result, never reformat or combine accounts
- spending questions -> call get_recent_transactions with specific category
- set_reminder ONLY when user explicitly asks, or a real future action needs tracking — never to defer a decision
- give a clear yes/no on purchase decisions with reasoning; if no, suggest when it might be possible
- tone: brief, direct, friendly

Purchase decisions: call get_account_balance + get_upcoming_bills first, reference savings commitments, show Rs.X impact on goal."""
    if memory.summary:
        p += f"""

Last session: {memory.summary}
Commitments: {memory.commitments}
Goals: {memory.goals}
Patterns: {memory.observed_patterns}

Numbers above are stale — fetch fresh via tools. Reference commitments explicitly when relevant."""
    return p

def build_transcript(messages: list) -> str:
    return "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
        if isinstance(m, dict) and m.get("role") in ("user","assistant")
        and isinstance(m.get("content"), str) and m["content"].strip()
    )

def sync_memory(existing: Memory, messages: list) -> Memory:
    has    = bool(existing.summary)
    block  = f"Existing memory:\n{json.dumps(asdict(existing), indent=2)}\n\n" if has else ""
    action = "merge new observations, do not drop existing commitments" if has else "extract key information"
    prompt = f"""Finance conversation — {action}. Return ONLY valid JSON, no markdown.

{block}Conversation:
{build_transcript(messages)}

Return: {{"summary":"2-3 lines on decisions and plans — no balance amounts or bill totals","goals":[{{"goal_id":"g1","description":"...","target_amount":1500000,"status":"active"}}],"commitments":[{{"commitment_id":"c1","action_item":"...","frequency":"one-time","due_date":"YYYY-MM-DD"}}],"observed_patterns":[{{"category":"...","observation":"...","confidence_score":"high"}}]}}

Rules:
- target_amount always 1500000
- due_date in YYYY-MM-DD always
- summary must NOT contain account balances or bill totals — those go stale
- capture ALL commitments including behavioural ones like spending cuts
- only store commitments that require a future action — not decisions already made
- never drop existing commitments when merging"""
    try:
        raw = client.chat.completions.create(model=MODEL, messages=[{"role":"user","content":prompt}], temperature=0).choices[0].message.content.strip()
    except Exception as e:
        print(f"[MEMORY] sync failed: {e}"); return existing
    raw = re.sub(r"```[\w]*\n?|```", "", raw).strip()
    try:
        data  = json.loads(raw)
        valid = {k: v for k, v in data.items() if k in Memory.__dataclass_fields__}
        mem   = Memory(**valid)
        print(f"\n[MEMORY] Synced:\n{json.dumps(data, indent=2)}")
        return mem
    except (json.JSONDecodeError, TypeError) as e:
        print(f"[MEMORY] bad JSON: {e} | raw: {raw[:200]}")
        existing.summary += " | Session update failed to parse."
        return existing

def call_llm_with_retry(messages: list):
    """
    Retry once if Groq rejects due to days-as-string tool validation error.
    Catches both known Groq error formats for this failure.
    """
    for attempt in range(2):
        try:
            return client.chat.completions.create(
                model=MODEL, messages=messages,
                tools=TOOL_DEFS, tool_choice="auto"
            )
        except Exception as e:
            err = str(e)
            # FIX: broadened to catch both Groq error message formats for days-as-string
            days_error = ("expected integer" in err or "tool_use_failed" in err) and "days" in err
            if attempt == 0 and days_error:
                print("[FINNO] days type error from Groq, injecting hint and retrying")
                messages = messages + [{"role":"user","content":"days parameter must be integer e.g. 30 not '30'. Retry."}]
                continue
            print(f"[FINNO] LLM failed: {e}"); return None
    return None

def agent_turn(messages: list) -> list:
    response = call_llm_with_retry(messages)
    if not response:
        messages.append({"role":"assistant","content":"Something went wrong, please try again."}); return messages

    iteration, MAX_ITER = 0, 4
    while response.choices[0].finish_reason == "tool_calls":
        iteration += 1
        if iteration > MAX_ITER:
            messages.append({"role":"assistant","content":"Too many tool calls, please try again."}); return messages

        msg = response.choices[0].message
        normalized = []
        for tc in msg.tool_calls:
            try: parsed = json.loads(tc.function.arguments)
            except json.JSONDecodeError: parsed = {}
            parsed = safe_args(tc.function.name, parsed)
            normalized.append({"id":tc.id,"type":"function","function":{"name":tc.function.name,"arguments":json.dumps(parsed)}})

        messages.append({"role":"assistant","content":msg.content or "","tool_calls":normalized})
        results = []
        for tc in msg.tool_calls:
            try: args = json.loads(tc.function.arguments)
            except json.JSONDecodeError: args = {}
            results.append({"role":"tool","tool_call_id":tc.id,"content":execute_tool(tc.function.name, args)})
        messages.extend(results)

        response = call_llm_with_retry(messages)
        if not response:
            messages.append({"role":"assistant","content":"Something went wrong, please try again."}); return messages

    final = response.choices[0].message.content
    messages.append({"role":"assistant","content":final})
    print(f"\n[FINNO] {final}")
    return messages

def run_session(session_num: int):
    print(f"\n{'='*50}\nFINNO — Session {session_num}\n{'='*50}\n")
    memory = load_memory()
    print(f"[MEMORY] Loaded: {memory.summary or 'none'}")
    messages = [{"role":"system","content":build_prompt(memory if memory.summary else Memory(), session_num)}]

    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit","quit"): break
        messages.append({"role":"user","content":user_input})
        messages = agent_turn(messages)

    memory = sync_memory(memory, messages)
    save_memory(memory)
    print("\n[MEMORY] Saved.")

    transcript_path = f"session_{session_num}_transcript.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"FINNO — Session {session_num} Transcript\n")
        f.write(f"Date: {SCENARIO_DATE.get(session_num, 'unknown')}\n")
        f.write("="*50 + "\n\n")
        f.write(build_transcript(messages))
    print(f"[FINNO] Transcript saved to {transcript_path}")

if __name__ == "__main__":
    import sys
    run_session(int(sys.argv[1]) if len(sys.argv) > 1 else 1)