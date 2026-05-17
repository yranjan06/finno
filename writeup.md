# Finno Writeup

---

## 1. Memory: What did you store after Session 1, and what did you deliberately NOT store? Why?

**Stored:**
- `summary` — 2-3 line narrative of key decisions (e.g. "Priya committed to saving Rs.30,000 to house fund on the 25th and cutting food delivery spend in half")
- `goals` — structured goal objects with target amounts and status (house down payment, Rs.15L in 2 years)
- `commitments` — explicit promises made: transfer amount, date, frequency
- `observed_patterns` — spending behaviour observations (e.g. food delivery averaging Rs.12,240/month, consistently on Swiggy/Zomato)

**Deliberately NOT stored:**
- Account balances — stale within hours, always fetched fresh via `get_account_balance`
- Transaction lists — change every day, always fetched via `get_recent_transactions`
- Upcoming bills — change as bills get paid (rent disappears between Session 1 and 2), always fetched via `get_upcoming_bills`
- Exact amounts from tool responses — if Priya's checking account was Rs.1,28,000 on Monday and we store it, we'd quote a wrong number on Thursday after rent clears

**Why this boundary:** Memory is for things that don't change without Priya saying so — her goals, her commitments, her patterns. Live financial state belongs to tools. Quoting stale balances in a finance agent is not just wrong, it's a trust-breaking failure.

---

## 2. Tools vs LLM: One decision given to the LLM, one kept as code. Why each?

**Given to LLM — whether the MacBook purchase conflicts with the savings commitment:**
This is a judgment call requiring context synthesis: current balance, remaining bills, the Rs.30,000 commitment made three days ago, the two-year house goal. No deterministic rule can weigh all of this. The LLM reads the memory, fetches fresh numbers, and reasons about trade-offs. That's exactly what LLMs are good at.

**Kept as code — summing food delivery spend from transactions:**
```python
result = {
    "total_spent": sum(abs(t["amount"]) for t in filtered),
    "transaction_count": len(filtered)
}
```
Asking an LLM to add up Rs.1,200 + Rs.1,800 + Rs.1,100... is slow, costs tokens, and can hallucinate. Python sums a list of integers without error. The rule: if a 5-line Python expression handles it exactly, don't call the LLM.

---

## 3. AI Usage: Which parts were AI-generated? One example where you rejected AI's suggestion.

**AI-assisted parts:**
- Initial scaffold of the `Memory` dataclass and `sync_memory` prompt structure (generated with Claude, then modified)
- The Groq tool-call normalization loop (AI suggested the pattern, I adapted it)
- The `build_transcript` function (generated, kept as-is — simple enough to trust)

**One rejection:**
Claude suggested storing the exact account balance in memory after Session 1:
```json
"last_known_balance": { "checking": 128000, "savings": 145000 }
```
with a note to "use as fallback if tool call fails."

I rejected this because a fallback balance is worse than no balance in a finance context. If the tool fails and we quote Rs.1,28,000 when the real balance is Rs.99,820 (after rent), Priya might make a Rs.80,000 purchase thinking she has more than she does. Failing loudly ("I couldn't fetch your balance right now") is safer than failing silently with stale data. The "helpful fallback" is actually a liability.

---

## 4. One Week More: What one thing would you redesign and why?

**The `sync_memory` LLM extraction step.**

Right now, after every session, I send the full conversation transcript to the LLM and ask it to extract structured memory. This works, but it has two problems:

1. **It runs once at the end.** If the session crashes mid-way, nothing is saved.
2. **It's extracting from a transcript**, which means the LLM is re-reading conversation it already processed, looking for things worth remembering after the fact.

With another week I'd move to **incremental memory writes during the session** — after each assistant turn, a lightweight classifier checks: "did a commitment just get made? did the user state a goal? did a pattern get confirmed?" If yes, append to memory immediately. This gives you crash-safe persistence, smaller extraction prompts, and more reliable structured output because you're capturing intent at the moment it's expressed, not reconstructing it from a full transcript 4 turns later.

The data model stays the same. Only when memory is written changes.