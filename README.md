# Finno

A personal finance agent that remembers you across sessions.
Holds two conversations three days apart and demonstrates it actually learned something from the first.

---

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

---

## How to Run

### Session 1 — Monday Nov 3

make sure `CURRENT_SESSION = 1` in `tools.py` (default)

```bash
# interactive mode
python agent.py 1

# automated test mode (runs exact sessions.md turns)
python test.py 1
```

### Session 2 — Thursday Nov 6

flip `CURRENT_SESSION = 2` in `tools.py` first , then:

```bash
# interactive mode
python agent.py 2

# automated test mode
python test.py 2
```

memory persists automatically between sessions via `finno_memory.json`

---

## Project Structure

```text
finno/
├── agent.py          # agent loop , memory layer , tool dispatch , prompts
├── tools.py          # provided mock tools , do not modify
├── sessions.md       # provided session scripts , do not modify
├── test.py           # automated test runner for assignment sessions
├── requirements.txt  # dependencies
├── .env.example      # env variable template
└── finno_memory.json # auto created after session 1
```

---

## Architecture Decisions

**Memory layer**
stores goals, commitments, observed patterns after session 1.
never stores balance, bills, transactions — those go stale and always get fetched fresh via tools.

**Tool vs LLM**
math and date filtering done in code.
LLM only called for judgment — what to say, what to remember, whether a purchase conflicts with a commitment.

**No frameworks**
agent loop written from scratch. no langchain, llamaindex, crewai.
groq + llama-3.3-70b for fast, free inference.

---

## What gets remembered

after session 1 finno saves:
- savings goals and target amounts
- commitments made (transfer amounts, dates)
- spending patterns observed
- session summary

after session 2 finno updates memory with new observations.

---

## Requirements

- python 3.10+
- groq api key (free at console.groq.com)
