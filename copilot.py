"""
AI Growth Copilot: Gemini + function calling over the app's live data.

Design:
- The model never sees a static dump. It must call tools, which run the same metric code
  as the dashboard on the CURRENT database contents and the selected as-of date.
- Arithmetic goes through a `calculate` tool, so numbers are computed, not guessed.
- Write actions (tasks, campaign status) are only PROPOSED by the model; the user confirms
  in the UI before anything is saved.
- `get_data_coverage` tells the model what the data cannot answer (cash receipts, spend,
  causality), so it can say "the data can't tell us" instead of inventing.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import uuid
from datetime import date, datetime

import numpy as np
import pandas as pd

import insights as ins
import sponsor_data as sd
import store

MAX_ROWS = 60


# ---------------------------------------------------------------------------
def jsonable(obj):
    if isinstance(obj, pd.DataFrame):
        df = obj.head(MAX_ROWS)
        return {"rows": [jsonable(r) for r in df.to_dict(orient="records")],
                "row_count": int(len(obj)), "truncated": bool(len(obj) > MAX_ROWS)}
    if isinstance(obj, pd.Series):
        return jsonable(obj.to_dict())
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat() if not pd.isna(obj) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if (obj is None or math.isnan(obj)) else round(float(obj), 4)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if obj is pd.NaT or (obj is not None and not isinstance(obj, (str, int, bool)) and pd.isna(obj)):
        return None
    return obj


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
        ast.FloorDiv: operator.floordiv}
_FUNCS = {"round": round, "min": min, "max": max, "abs": abs, "sum": lambda *a: sum(a)}


def safe_eval(expr: str) -> float:
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError("Only numbers, + - * / ** % and round/min/max/abs/sum are allowed")
    if len(expr) > 300:
        raise ValueError("Expression too long")
    return ev(ast.parse(expr.replace(",", "").replace("₹", ""), mode="eval"))


# ---------------------------------------------------------------------------
class CopilotTools:
    """All tools read the database fresh on every call, so answers reflect edits immediately."""

    def __init__(self, engine, default_as_of: date, loader=None, app_loader=None):
        self.engine = engine
        self.default_as_of = default_as_of
        self.pending: list[dict] = []     # proposals awaiting user confirmation
        # loaders can be swapped for cached versions by the UI
        self.loader = loader or (lambda: store.load_source(self.engine))
        self.app_loader = app_loader or (lambda name: store.load_app_table(self.engine, name))
        self._memo = None

    def begin_turn(self):
        """Read the database once per user turn (fresh data, but not 10 reloads per answer)."""
        self._memo = None

    # helpers
    def _data(self):
        if self._memo is None:
            self._memo = self.loader()
        return self._memo

    def _snap(self, as_of: str | None):
        data = self._data()
        day = as_of or self.default_as_of
        s = sd.snapshot(data, day)
        return data, s

    def _event_start(self, data):
        return data["event"]["event_starts_at"].iloc[0]

    # ---- read tools -------------------------------------------------------
    def get_overview(self, as_of: str | None = None):
        data, s = self._snap(as_of)
        f = sd.weighted_forecast(s, self._event_start(data))
        f.pop("by_opportunity")
        h = sd.headline(s)
        h["cash_collected_inr"] = ins.cash_summary(s, self.app_loader("cash_receipts"))
        return {"headline": h, "forecast": f,
                "event": {"starts_at": self._event_start(data), "ends_at": data["event"]["event_ends_at"].iloc[0]},
                "targets_history": data["targets"]}

    def get_funnel(self, as_of: str | None = None):
        _, s = self._snap(as_of)
        return {"as_of": s.cutoff.date(), "funnel": sd.funnel(s),
                "definitions": "Brand-level counts up to qualification (unique brands), opportunity-level after. "
                               "'Reached proposal/negotiation' counts deals that ever reached the stage, even if later lost."}

    def get_campaign_performance(self, as_of: str | None = None):
        _, s = self._snap(as_of)
        ct = sd.campaign_table(s)
        plans = self.app_loader("campaign_plans")
        return {"as_of": s.cutoff.date(), "campaigns": ct,
                "recommendations": ins.recommendations(s), "rules": ins.RULES,
                "plans_and_spend": ins.spend_summary(plans, ct),
                "attribution_note": "Reply/meeting columns count brands with that event in the campaign (a brand touched "
                                    "by two campaigns counts in both); confirmed and value use the opportunity's "
                                    "originating campaign. Association is observational, not causal."}

    def get_pipeline(self, as_of: str | None = None, stage: str | None = None,
                     sponsor_campaign_id: str | None = None, owner: str | None = None):
        _, s = self._snap(as_of)
        o = s.opportunities.copy()
        o["days_in_stage"] = (pd.Timestamp(s.cutoff) - o["stage_since"]).dt.days
        if stage:
            o = o[o["stage"] == stage]
        if sponsor_campaign_id:
            o = o[o["sponsor_campaign_id"] == sponsor_campaign_id]
        if owner:
            o = o[o["deal_owner_name"].str.lower() == owner.lower()]
        cols = ["opportunity_id", "opportunity_name", "brand_name", "originating_campaign_name", "sponsor_campaign_id",
                "support_type", "stage", "proposed_value_inr", "confirmed_value_inr", "deal_owner_name",
                "stage_since", "days_in_stage", "created_at"]
        return {"as_of": s.cutoff.date(), "opportunities": o[cols].sort_values("proposed_value_inr", ascending=False),
                "stage_counts": o["stage"].value_counts().to_dict(),
                "total_proposed_value_inr": int(o["proposed_value_inr"].sum())}

    def get_stale_deals(self, as_of: str | None = None, days: int = sd.STALE_DAYS):
        _, s = self._snap(as_of)
        st = sd.stale_opportunities(s, int(days))
        return {"as_of": s.cutoff.date(), "threshold_days": int(days), "stale": st,
                "evidence": "In this dataset no won deal sat more than 5 days in a stage; none of the deals idle "
                            "for 7+ days ever closed."}

    def get_stage_conversion(self, as_of: str | None = None):
        _, s = self._snap(as_of)
        ct = sd.cycle_times(s)
        return {"as_of": s.cutoff.date(), "stage_conversion": sd.stage_conversion(s),
                "cycle_days_create_to_confirm": ct["days_create_to_confirm"].describe().to_dict() if len(ct) else None,
                "cycle_days_proposal_to_confirm": ct["days_proposal_to_confirm"].describe().to_dict() if len(ct) else None}

    def get_breakdown(self, by: str, as_of: str | None = None):
        _, s = self._snap(as_of)
        if by == "owner":
            return {"as_of": s.cutoff.date(), "by_owner": sd.owner_table(s)}
        if by == "industry":
            return {"as_of": s.cutoff.date(), "by_industry": sd.industry_table(s)}
        return {"error": "by must be 'owner' or 'industry'"}

    def get_weekly_trend(self, as_of: str | None = None):
        _, s = self._snap(as_of)
        return {"as_of": s.cutoff.date(), "weekly": sd.weekly_trend(s)}

    def compare_dates(self, date_from: str, date_to: str | None = None):
        data = self._data()
        a = sd.snapshot(data, date_from)
        b = sd.snapshot(data, date_to or self.default_as_of)
        return ins.compare(a, b)

    def get_brand(self, query: str):
        data = self._data()
        b = data["brands"]
        m = b[(b["brand_id"].str.upper() == query.upper()) | (b["brand_name"].str.lower().str.contains(query.lower(), regex=False))]
        if m.empty:
            return {"found": False, "message": f"No brand matches '{query}'."}
        if len(m) > 5:
            return {"found": True, "multiple": m[["brand_id", "brand_name", "industry"]]}
        out = []
        cutoff = sd.cutoff_for(self.default_as_of)
        for _, br in m.iterrows():
            bid = br["brand_id"]
            i = data["interactions"]
            i = i[(i["brand_id"] == bid) & (i["occurred_at"] <= cutoff)].sort_values("occurred_at")
            q = data["qualification"]
            q = q[(q["brand_id"] == bid) & (q["effective_at"] <= cutoff)].sort_values("effective_at")
            oh = data["opp_history"]
            oh = oh[(oh["brand_id"] == bid) & (oh["effective_at"] <= cutoff)].sort_values("effective_at")
            out.append({"brand": br, "contacts": data["contacts"][data["contacts"]["brand_id"] == bid],
                        "interactions": i[["occurred_at", "campaign_name", "contact_name", "event_type", "outcome"]],
                        "qualification_history": q[["effective_at", "qualification_status", "reason"]],
                        "opportunity_history": oh[["effective_at", "opportunity_name", "stage", "proposed_value_inr", "confirmed_value_inr"]]})
        return {"found": True, "as_of": cutoff.date(), "brands": out}

    def get_tasks(self, status: str | None = None, owner: str | None = None):
        t = self.app_loader("tasks")
        if status:
            t = t[t["status"] == status]
        if owner:
            t = t[t["owner"].fillna("").str.lower() == owner.lower()]
        return {"tasks": t.sort_values("due_date"), "counts_by_status": t["status"].value_counts().to_dict()}

    def get_data_coverage(self):
        data = self._data()
        cr = self.app_loader("cash_receipts")
        plans = self.app_loader("campaign_plans")
        return {
            "event": data["event"].iloc[0], "record_counts": {k: len(v) for k, v in data.items()},
            "cash_receipts_recorded": int(len(cr)),
            "campaigns_with_spend_entered": int(plans["spend_inr"].notna().sum()),
            "can_answer": ["funnel counts and conversion by campaign/owner/industry", "deal stages, values, stale deals",
                           "target vs actual (qualified brands, confirmed partnerships)", "point-in-time snapshots and changes",
                           "weighted forecast of partnerships/value", "tasks"],
            "cannot_answer_from_data": [
                "cash actually collected (no bank-receipt data) unless receipts are recorded in the app",
                "cost, ROI or cost per deal (no spend data) unless spend is entered in campaign plans",
                "causal impact of a campaign or sponsor activation (association only)",
                "anything about real companies: brands and people are fictional",
                "sponsor budgets, reasons for decisions or sentiment beyond the recorded outcome labels"],
            "caveats": ["Synthetic data; 24 confirmed deals is a small sample.",
                        "Reported partnership value includes in-kind support and is not cash received."],
        }

    def calculate(self, expression: str):
        try:
            return {"expression": expression, "result": safe_eval(expression)}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # ---- write proposals (require user confirmation in the UI) -----------
    def propose_task(self, title: str, owner: str | None = None, due_date: str | None = None,
                     priority: str = "medium", description: str = "", sponsor_campaign_id: str | None = None,
                     opportunity_id: str | None = None):
        if priority not in ("high", "medium", "low"):
            priority = "medium"
        p = {"proposal_id": uuid.uuid4().hex[:6], "kind": "task",
             "fields": {"title": title[:200], "owner": owner, "due_date": due_date, "priority": priority,
                        "description": description, "sponsor_campaign_id": sponsor_campaign_id,
                        "opportunity_id": opportunity_id}}
        self.pending.append(p)
        return {"status": "awaiting_user_confirmation", "proposal_id": p["proposal_id"],
                "message": "Shown to the user with Confirm / Discard buttons. Not saved yet."}

    def propose_campaign_status(self, sponsor_campaign_id: str, status: str, reason: str):
        if status not in ("active", "scale", "change", "stop"):
            return {"error": "status must be active, scale, change or stop"}
        p = {"proposal_id": uuid.uuid4().hex[:6], "kind": "campaign_status",
             "fields": {"sponsor_campaign_id": sponsor_campaign_id, "status": status, "notes": reason}}
        self.pending.append(p)
        return {"status": "awaiting_user_confirmation", "proposal_id": p["proposal_id"],
                "message": "Shown to the user with Confirm / Discard buttons. Not saved yet."}


def apply_proposal(engine, p: dict) -> str:
    f = p["fields"]
    if p["kind"] == "task":
        due = pd.to_datetime(f.get("due_date")).date() if f.get("due_date") else None
        tid = store.add_task(engine, actor="copilot", title=f["title"], owner=f.get("owner"), due_date=due,
                             priority=f.get("priority", "medium"), description=f.get("description"),
                             sponsor_campaign_id=f.get("sponsor_campaign_id"), opportunity_id=f.get("opportunity_id"),
                             source="copilot", status="todo")
        return f"Task #{tid} created: {f['title']}"
    if p["kind"] == "campaign_status":
        store.save_plan(engine, f["sponsor_campaign_id"], actor="copilot", status=f["status"], notes=f["notes"])
        return f"Campaign {f['sponsor_campaign_id']} marked '{f['status']}'"
    return "Unknown proposal"


# ---------------------------------------------------------------------------
# Function declarations (JSON schema)
D = "Snapshot date YYYY-MM-DD (end of day IST). Omit to use the app's selected as-of date."
TOOL_SPECS = [
    ("get_overview", "Headline KPIs, target vs actual, confirmed value, open pipeline, cash-collected status, and the weighted forecast.",
     {"as_of": {"type": "string", "description": D}}, []),
    ("get_funnel", "Overall sponsor funnel with stage counts and conversion rates.",
     {"as_of": {"type": "string", "description": D}}, []),
    ("get_campaign_performance", "Per-campaign metrics, scale/change/stop recommendations with reasons, rules, and any entered budget/spend.",
     {"as_of": {"type": "string", "description": D}}, []),
    ("get_pipeline", "List opportunities with stage, values, owner and days in current stage; optional filters.",
     {"as_of": {"type": "string", "description": D},
      "stage": {"type": "string", "description": "prospecting, contacted, proposal_sent, negotiating, partner_confirmed, lost or withdrawn"},
      "sponsor_campaign_id": {"type": "string", "description": "e.g. SC01"},
      "owner": {"type": "string", "description": "deal owner name"}}, []),
    ("get_stale_deals", "Open deals idle in their stage for at least N days (default 7).",
     {"as_of": {"type": "string", "description": D}, "days": {"type": "integer"}}, []),
    ("get_stage_conversion", "Stage-to-stage conversion, win rates and cycle times.",
     {"as_of": {"type": "string", "description": D}}, []),
    ("get_breakdown", "Performance by deal owner or by brand industry.",
     {"by": {"type": "string", "enum": ["owner", "industry"]}, "as_of": {"type": "string", "description": D}}, ["by"]),
    ("get_weekly_trend", "Weekly counts of outreach, replies, meetings, confirmations and confirmed value.",
     {"as_of": {"type": "string", "description": D}}, []),
    ("compare_dates", "What changed between two dates: headline deltas, per-campaign deltas and deals that moved stage.",
     {"date_from": {"type": "string"}, "date_to": {"type": "string", "description": "defaults to the selected as-of date"}}, ["date_from"]),
    ("get_brand", "Full history for one brand by name or ID: contacts, interactions, qualification and opportunity history.",
     {"query": {"type": "string"}}, ["query"]),
    ("get_tasks", "List tasks in the management tool, optionally filtered by status (todo, in_progress, blocked, done) or owner.",
     {"status": {"type": "string"}, "owner": {"type": "string"}}, []),
    ("get_data_coverage", "What the data contains and what it CANNOT answer. Call when a question may be outside the data.", {}, []),
    ("calculate", "Evaluate an arithmetic expression exactly. Use for every computation (sums, ratios, percentages, projections).",
     {"expression": {"type": "string", "description": "e.g. (785000+670000)/2240000*100"}}, ["expression"]),
    ("propose_task", "Propose a task for the user to confirm. Never claim a task exists until the user confirms.",
     {"title": {"type": "string"}, "owner": {"type": "string"}, "due_date": {"type": "string", "description": "YYYY-MM-DD"},
      "priority": {"type": "string", "enum": ["high", "medium", "low"]}, "description": {"type": "string"},
      "sponsor_campaign_id": {"type": "string"}, "opportunity_id": {"type": "string"}}, ["title"]),
    ("propose_campaign_status", "Propose marking a campaign scale/change/stop/active, for user confirmation.",
     {"sponsor_campaign_id": {"type": "string"}, "status": {"type": "string", "enum": ["active", "scale", "change", "stop"]},
      "reason": {"type": "string"}}, ["sponsor_campaign_id", "status", "reason"]),
]


def system_prompt(as_of: date, owners: list[str], campaigns: pd.DataFrame) -> str:
    camp = "; ".join(f"{r.sponsor_campaign_id}={r.campaign_name} ({r.channel})" for r in campaigns.itertuples())
    return f"""You are the Growth Analyst & Copilot inside a sponsorship command center for a college festival.
The selected snapshot date is {as_of.isoformat()} (end of day, IST). Campaigns: {camp}. Team: {', '.join(owners)}.

How to work:
- Answer ONLY from tool results on the current data. Call tools before stating any number; never use outside or generic knowledge as if it were data.
- Use `calculate` for every arithmetic step (totals, ratios, differences, projections). Never do mental math.
- Say which snapshot date your numbers are for. Mention the tool-derived evidence (e.g. "SC01: 91 brands contacted, 0 confirmed").
- Separate EVIDENCE (what the data shows) from ASSUMPTION or JUDGEMENT (your interpretation). Label them.
- If the data cannot answer (cash actually collected, spend/ROI, causal impact, real-world companies, anything not in the tools), say so plainly, explain what is missing, and suggest what data would answer it. Call `get_data_coverage` when unsure. Never invent figures.
- Note small samples (e.g. fewer than ~10 brands or deals) as low confidence.
- Recommendations: say what to scale, change or stop, with the numbers behind it, consistent with the campaign recommendations tool.
- Execution: when an action would help, offer it and call `propose_task` or `propose_campaign_status`. These only create a proposal the user must confirm; say "I've proposed..." not "I've created...".
- Reported partnership value is not cash received. A positive reply is not qualification; qualification is not a confirmed deal.
- Be concise: short paragraphs or bullets, figures in INR with Indian grouping where natural (₹22.4L, ₹1.2 Cr)."""


def declarations():
    from google.genai import types
    out = []
    for name, desc, props, req in TOOL_SPECS:
        schema = {"type": "object", "properties": props}
        if req:
            schema["required"] = req
        out.append(types.FunctionDeclaration(name=name, description=desc, parameters_json_schema=schema))
    return [types.Tool(function_declarations=out)]


TRANSIENT = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded", "high demand", "timed out", "timeout",
             "504", "DEADLINE_EXCEEDED", "Deadline", "500", "INTERNAL", "502", "Bad Gateway", "Connection")


def _generate(client, model, fallbacks, history, config, base, on_step):
    """Call Gemini with retries on overload (503/429/timeouts) and fall back to backup models.
    Returns (response, model_used, config_used)."""
    import time
    from google.genai import types
    models = [model] + [m for m in (fallbacks or []) if m and m != model]
    last = None
    for m in models:
        for attempt, wait in enumerate((0, 4)):
            if wait:
                if on_step:
                    on_step(f"{m} is busy, retrying in {wait}s (attempt {attempt + 1}/2)…")
                time.sleep(wait)
            try:
                return client.models.generate_content(model=m, contents=history, config=config), m, config
            except Exception as e:  # noqa: BLE001
                last = e
                msg = str(e)
                if "thinking" in msg.lower() and getattr(config, "thinking_config", None) is not None:
                    config = types.GenerateContentConfig(**base)   # model rejects thinking level: drop it
                    continue
                if "404" in msg or "NOT_FOUND" in msg:
                    break                                           # model unavailable: try next model
                if not any(t.lower() in msg.lower() for t in TRANSIENT):
                    raise                                           # real error (bad key etc.): surface it
        if on_step and m != models[-1]:
            on_step(f"Switching to backup model {models[models.index(m) + 1]}…")
    raise last


def run_turn(client, model: str, tools: CopilotTools, history: list, user_text: str, sys_prompt: str,
             max_steps: int = 8, on_step=None, fallback_models: list[str] | None = None):
    """One user turn with a manual function-calling loop.
    Returns (answer_text, updated_history, trace) where trace lists tool calls made."""
    from google.genai import types
    history = list(history) + [types.Content(role="user", parts=[types.Part(text=user_text)])]
    base = dict(system_instruction=sys_prompt, tools=declarations(), temperature=0.2,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    try:  # low thinking keeps answers fast; fall back if a model does not accept it
        config = types.GenerateContentConfig(**base, thinking_config=types.ThinkingConfig(thinking_level="LOW"))
    except Exception:  # noqa: BLE001
        config = types.GenerateContentConfig(**base)
    tools.begin_turn()
    trace = []
    for step in range(max_steps):
        if on_step:
            on_step(f"Step {step + 1}: asking the model…")
        resp, model, config = _generate(client, model, fallback_models, history, config, base, on_step)
        cand = resp.candidates[0].content if resp.candidates else None
        calls = resp.function_calls or []
        if cand is not None:
            history.append(cand)
        if not calls:
            return (resp.text or "(no answer)"), history, trace
        parts = []
        for fc in calls:
            args = dict(fc.args or {})
            if on_step:
                on_step(f"Running {fc.name}({', '.join(f'{k}={v}' for k, v in args.items())})")
            fn = getattr(tools, fc.name, None)
            try:
                result = fn(**args) if fn and fc.name in {t[0] for t in TOOL_SPECS} else {"error": f"unknown tool {fc.name}"}
            except Exception as e:  # noqa: BLE001
                result = {"error": f"{type(e).__name__}: {e}"}
            payload = jsonable(result)
            trace.append({"tool": fc.name, "args": args, "result_preview": json.dumps(payload, default=str)[:600]})
            parts.append(types.Part.from_function_response(name=fc.name, response={"result": payload}))
        history.append(types.Content(role="user", parts=parts))
    return "I hit the step limit while analysing. Try a narrower question.", history, trace
