# Finno

A personal finance agent that remembers you across sessions.
Holds two conversations three days apart and demonstrates it actually learned something from the first.

---



[Uploading Kapture 2026-05-17 at 21.28.22.mp4…](https://github.com/user-attachments/assets/eabe5cdf-434d-42f8-9753-be9be9d8d7b6)



## Setup

```bash
git clone https://github.com/yranjan06/finno.git
cd finno

python -m venv venv
source venv/bin/activate  # windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# open .env and add your GROQ_API_KEY
# get a free key at https://console.groq.com
```

> Tested on Python 3.11. Requires Python 3.10+.

---

## How to Run

### Session 1 — Monday Nov 3

Make sure `CURRENT_SESSION = 1` in `tools.py` (default).

```bash
# interactive mode
python agent.py 1

# automated test mode (runs exact sessions.md turns)
python test.py 1
```

After Session 1, `finno_memory.json` is written to disk automatically.

### Session 2 — Thursday Nov 6

Flip `CURRENT_SESSION = 2` in `tools.py` first, then:

```bash
# interactive mode
python agent.py 2

# automated test mode
python test.py 2
```

Memory persists automatically between sessions via `finno_memory.json`.
Transcripts are saved automatically as `session_1_transcript.txt` and `session_2_transcript.txt`.

---

## Project Structure

```text
finno/
├── agent.py                      # agent loop, memory layer, tool dispatch, prompts
├── tools.py                      # provided mock tools, do not modify
├── sessions.md                   # provided session scripts, do not modify
├── test.py                       # automated test runner for assignment sessions
├── writeup.md                    # one-page writeup answering the 4 assignment questions
├── requirements.txt              # dependencies
├── .env.example                  # env variable template
├── finno_memory.example.json     # sample memory output from Session 1 (for reference)
├── session_1_transcript.txt      # auto-created after running Session 1
├── session_2_transcript.txt      # auto-created after running Session 2
└── finno_memory.json             # auto-created after Session 1 (gitignored)
```

---

## Architecture

### Agent Loop
Raw loop written from scratch — no LangChain, LlamaIndex, or CrewAI.
Each user turn calls `agent_turn()`, which runs a tool-calling loop with `MAX_ITER = 4`.
All LLM calls go through `call_llm_with_retry()` which catches Groq tool validation errors and retries once with a correction hint.

### Memory Layer
After each session, `sync_memory()` sends the full conversation to the LLM and extracts structured JSON:

```json
{
  "summary": "2-3 lines on decisions — no balance amounts",
  "goals": [{ "goal_id": "g1", "target_amount": 1500000, "status": "active" }],
  "commitments": [{ "action_item": "Transfer Rs.30,000 to house fund", "due_date": "2025-11-25" }],
  "observed_patterns": [{ "category": "spending", "observation": "High food delivery spend" }]
}
```

**What gets stored:** goals, commitments (transfers AND behavioural like spending cuts), observed patterns, summary.

**What never gets stored:** account balances, bill totals, transaction lists — all fetched fresh via tools every session because they change daily.

### Tool vs LLM Split
Math done in code — transaction filtering, category summing, date cutoffs.
LLM called only for judgment — what to say, whether a purchase conflicts with a goal, what to remember.

### Tool Dispatch
```
get_account_balance     → always fresh, never from memory
get_recent_transactions → filtered by date cutoff in code, category summed in code
get_upcoming_bills      → always fresh (changes as bills are paid between sessions)
set_reminder            → only when user explicitly asks or a real commitment needs tracking
```

---

## What Session 2 Demonstrates

Given one message — *"My colleague is selling his MacBook for ₹80,000. Should I buy it?"* — the agent:

1. **Memory** — loads the savings plan from Session 1 without being told
2. **Judgment** — connects the purchase to the ₹30,000 house fund commitment unprompted
3. **Tool discipline** — fetches fresh balance (₹99,820, not stale ₹1,28,000) and current bills (rent already paid)
4. **Clear answer** — gives a direct no with reasoning, does not set a spurious reminder to defer the decision

---

## Requirements

- Python 3.10+
- Groq API key (free at console.groq.com)


