"""
Persistence for the Sponsor Growth Center.

- Works on SQLite locally (default) and on Postgres/Supabase when DATABASE_URL is set.
- Source tables mirror the provided workbook sheets (raw rows, duplicates kept, so the
  cleaning rules are applied at read time exactly as on the original data).
- Changes to full-state histories (opportunity stage, brand qualification) are APPENDED
  as new versions, never overwritten, so point-in-time snapshots stay correct.
- App tables hold what the source does not: tasks, campaign plans (budget/spend/status),
  cash receipts and a change log.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import (Column, Date, DateTime, Integer, MetaData, String, Table, Text,
                        create_engine, delete, insert, inspect, select, update)
from sqlalchemy.engine import Engine

import sponsor_data as sd

BASE = Path(__file__).parent
SOURCE_XLSX = BASE / "data" / "Sponsor_Dataset.xlsx"
SOURCE_TABLES = list(sd.SHEETS.keys())  # event, targets, brands, ...

meta = MetaData()
tasks_t = Table(
    "tasks", meta,
    Column("task_id", Integer, primary_key=True, autoincrement=True),
    Column("title", String(200), nullable=False),
    Column("description", Text),
    Column("owner", String(80)),
    Column("due_date", Date),
    Column("status", String(20), default="todo"),        # todo | in_progress | blocked | done
    Column("priority", String(10), default="medium"),    # high | medium | low
    Column("sponsor_campaign_id", String(20)),
    Column("opportunity_id", String(20)),
    Column("source", String(20), default="manual"),      # manual | copilot | seed
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
)
plans_t = Table(
    "campaign_plans", meta,
    Column("sponsor_campaign_id", String(20), primary_key=True),
    Column("status", String(20), default="active"),      # active | scale | change | stop
    Column("budget_inr", Integer),
    Column("spend_inr", Integer),
    Column("target_confirmed", Integer),
    Column("target_value_inr", Integer),
    Column("notes", Text),
    Column("updated_at", DateTime),
)
cash_t = Table(
    "cash_receipts", meta,
    Column("receipt_id", Integer, primary_key=True, autoincrement=True),
    Column("opportunity_id", String(20), nullable=False),
    Column("amount_inr", Integer, nullable=False),
    Column("received_at", DateTime, nullable=False),
    Column("note", Text),
)
log_t = Table(
    "change_log", meta,
    Column("log_id", Integer, primary_key=True, autoincrement=True),
    Column("at", DateTime),
    Column("actor", String(40)),
    Column("action", String(60)),
    Column("detail", Text),
)
APP_TABLES = ["tasks", "campaign_plans", "cash_receipts", "change_log"]


# ---------------------------------------------------------------------------
def get_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{BASE / 'growth_center.db'}"
    url = url.strip()
    # Use the psycopg2 driver (in requirements.txt); SQLAlchemy 2.1 defaults to psycopg v3.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix):]
    return create_engine(url, pool_pre_ping=True)


def is_seeded(engine: Engine) -> bool:
    names = set(inspect(engine).get_table_names())
    return all(t in names for t in SOURCE_TABLES + APP_TABLES)


def seed(engine: Engine, reset: bool = False) -> None:
    """Load the original workbook into source tables and create app tables.
    reset=True restores the original data and clears tasks/plans/receipts."""
    if is_seeded(engine) and not reset:
        return
    raw = sd.load_workbook(SOURCE_XLSX)
    for key, df in raw.items():
        df.to_sql(key, engine, if_exists="replace", index=False)
    if reset:
        meta.drop_all(engine, tables=[tasks_t, plans_t, cash_t, log_t])
    meta.create_all(engine)
    now = datetime.now()
    with engine.begin() as c:
        for cid in raw["campaigns"]["sponsor_campaign_id"]:
            c.execute(insert(plans_t).values(sponsor_campaign_id=cid, status="active", updated_at=now))
        for t in _seed_tasks():
            c.execute(insert(tasks_t).values(**t, source="seed", created_at=now, updated_at=now))
        c.execute(insert(log_t).values(at=now, actor="system", action="seed",
                                       detail="Loaded original Sponsor_Dataset.xlsx" + (" (reset)" if reset else "")))


def _seed_tasks() -> list[dict]:
    """Simulated starter tasks inside the data window (labelled 'seed')."""
    d = lambda s: date.fromisoformat(s)
    return [
        dict(title="Send proposal follow-up to Evergreen Collective", owner="Riya Kapoor", due_date=d("2025-02-20"),
             status="done", priority="high", opportunity_id="O054", sponsor_campaign_id="SC03",
             description="Negotiation open since 13 Feb; confirm activation scope."),
        dict(title="Qualify inbound form submissions from this week", owner="Kabir Shah", due_date=d("2025-03-07"),
             status="done", priority="medium", sponsor_campaign_id="SC04", description="Check fit against partnership brief."),
        dict(title="Ask confirmed partners for one warm introduction each", owner="Riya Kapoor", due_date=d("2025-03-21"),
             status="in_progress", priority="high", sponsor_campaign_id="SC02",
             description="Warm introductions convert far better than cold outreach."),
        dict(title="Review cold email list: stop contacting non-responders", owner="Kabir Shah", due_date=d("2025-03-28"),
             status="todo", priority="medium", sponsor_campaign_id="SC01", description="Reply rate low; opt-outs rising."),
        dict(title="Prepare sponsor ROI recap template", owner="Nisha Rao", due_date=d("2025-04-18"),
             status="todo", priority="low", description="Footfall, leads captured and reach per partner."),
    ]


# ---------------------------------------------------------------------------
# Reads
def load_source(engine: Engine) -> dict[str, pd.DataFrame]:
    raw = {k: pd.read_sql_table(k, engine) for k in SOURCE_TABLES}
    return sd.clean(raw)


def data_version(engine: Engine) -> int:
    """Changes whenever anything is written (every write is logged), so cached reads stay correct."""
    from sqlalchemy import func
    with engine.connect() as c:
        return int(c.execute(select(func.max(log_t.c.log_id))).scalar() or 0)


def load_raw_table(engine: Engine, name: str) -> pd.DataFrame:
    return pd.read_sql_table(name, engine)


def load_app_table(engine: Engine, name: str) -> pd.DataFrame:
    df = pd.read_sql_table(name, engine)
    return df


def data_end(data: dict[str, pd.DataFrame], engine: Engine | None = None) -> date:
    """Latest date with any recorded activity (default 'as of' date)."""
    cands = [data["event"]["history_end"].iloc[0]]
    for k, col in [("interactions", "occurred_at"), ("qualification", "effective_at"),
                   ("opp_history", "effective_at"), ("targets", "effective_at")]:
        if len(data[k]):
            cands.append(data[k][col].max())
    if engine is not None:
        cr = load_app_table(engine, "cash_receipts")
        if len(cr):
            cands.append(pd.to_datetime(cr["received_at"]).max())
    return pd.Timestamp(max(cands)).date()


def owners(data: dict[str, pd.DataFrame]) -> list[str]:
    names = set()
    for k in ("brands", "campaigns", "opp_history"):
        names |= set(data[k]["owner_name"].dropna())
    return sorted(names)


def owner_id_for(data, name: str) -> str | None:
    for k in ("brands", "campaigns", "opp_history"):
        m = data[k].loc[data[k]["owner_name"] == name, "owner_id"]
        if len(m):
            return m.iloc[0]
    return None


# ---------------------------------------------------------------------------
# Writes (each one logged)
def _log(c, action: str, detail: str, actor: str = "user"):
    c.execute(insert(log_t).values(at=datetime.now(), actor=actor, action=action, detail=detail))


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"


def suggest_effective_at(data, as_of: date, entity_col: str, entity_id: str, table: str) -> datetime:
    """Default timestamp for a new history version: 18:00 on the as-of day, or 1 hour after
    the entity's latest version if that is later (so the new version is always the latest)."""
    ts = datetime.combine(as_of, datetime.min.time()) + timedelta(hours=18)
    h = data[table]
    prev = h.loc[h[entity_col] == entity_id, "effective_at"]
    if len(prev) and prev.max() >= ts:
        ts = prev.max().to_pydatetime() + timedelta(hours=1)
    return ts


def set_opportunity_stage(engine, data, opportunity_id: str, stage: str, proposed_value_inr: int,
                          owner_name: str, effective_at: datetime, actor: str = "user") -> str:
    if stage not in sd.STAGE_ORDER + sd.CLOSED_LOST:
        raise ValueError(f"Unknown stage {stage}")
    opp = data["opportunities"].set_index("opportunity_id").loc[opportunity_id]
    hid = _new_id("OHX")
    row = dict(opportunity_name=opp["opportunity_name"], brand_name=opp["brand_name"], stage=stage,
               proposed_value_inr=int(proposed_value_inr),
               confirmed_value_inr=int(proposed_value_inr) if stage == "partner_confirmed" else 0,
               owner_name=owner_name, effective_at=effective_at, history_id=hid,
               opportunity_id=opportunity_id, brand_id=opp["brand_id"], owner_id=owner_id_for(data, owner_name))
    with engine.begin() as c:
        pd.DataFrame([row]).to_sql("opp_history", c, if_exists="append", index=False)
        _log(c, "opportunity_stage", f"{opportunity_id} -> {stage} (₹{proposed_value_inr:,}) at {effective_at:%Y-%m-%d %H:%M}", actor)
    return hid


def add_opportunity(engine, data, brand_id: str, sponsor_campaign_id: str, support_type: str,
                    proposed_value_inr: int, owner_name: str, created_at: datetime, name: str | None = None) -> str:
    b = data["brands"].set_index("brand_id").loc[brand_id]
    camp = data["campaigns"].set_index("sponsor_campaign_id").loc[sponsor_campaign_id]
    contacts = data["contacts"][data["contacts"]["brand_id"] == brand_id]
    oid = _new_id("OX")
    opp = dict(opportunity_name=name or f"{b['brand_name']} festival partnership", brand_name=b["brand_name"],
               primary_contact_name=contacts["contact_name"].iloc[0] if len(contacts) else None,
               originating_campaign_name=camp["campaign_name"], support_type=support_type, created_at=created_at,
               opportunity_id=oid, brand_id=brand_id,
               primary_contact_id=contacts["contact_id"].iloc[0] if len(contacts) else None,
               sponsor_campaign_id=sponsor_campaign_id)
    hist = dict(opportunity_name=opp["opportunity_name"], brand_name=b["brand_name"], stage="prospecting",
                proposed_value_inr=int(proposed_value_inr), confirmed_value_inr=0, owner_name=owner_name,
                effective_at=created_at + timedelta(minutes=5), history_id=_new_id("OHX"), opportunity_id=oid,
                brand_id=brand_id, owner_id=owner_id_for(data, owner_name))
    with engine.begin() as c:
        pd.DataFrame([opp]).to_sql("opportunities", c, if_exists="append", index=False)
        pd.DataFrame([hist]).to_sql("opp_history", c, if_exists="append", index=False)
        _log(c, "opportunity_add", f"{oid} for {b['brand_name']} via {sponsor_campaign_id}")
    return oid


def set_qualification(engine, data, brand_id: str, status: str, reason: str, effective_at: datetime) -> str:
    b = data["brands"].set_index("brand_id").loc[brand_id]
    q = data["qualification"]
    last = q[q["brand_id"] == brand_id].sort_values("effective_at").tail(1)
    cid = last["sponsor_campaign_id"].iloc[0] if len(last) else None
    cname = last["source_campaign_name"].iloc[0] if len(last) else None
    hid = _new_id("QHX")
    row = dict(brand_name=b["brand_name"], qualification_status=status, reason=reason,
               source_campaign_name=cname, effective_at=effective_at, history_id=hid,
               brand_id=brand_id, sponsor_campaign_id=cid)
    with engine.begin() as c:
        pd.DataFrame([row]).to_sql("qualification", c, if_exists="append", index=False)
        _log(c, "qualification", f"{brand_id} -> {status}")
    return hid


def add_campaign(engine, name: str, channel: str, objective: str, audience: str, owner_name: str,
                 owner_id: str | None, start: datetime, end: datetime) -> str:
    cid = _new_id("SCX")[:9]
    row = dict(campaign_name=name, channel=channel, objective=objective, audience=audience, owner_name=owner_name,
               planned_start_at=start, planned_end_at=end, created_at=datetime.now(),
               sponsor_campaign_id=cid, owner_id=owner_id)
    with engine.begin() as c:
        pd.DataFrame([row]).to_sql("campaigns", c, if_exists="append", index=False)
        c.execute(insert(plans_t).values(sponsor_campaign_id=cid, status="active", updated_at=datetime.now()))
        _log(c, "campaign_add", f"{cid} {name}")
    return cid


def save_plan(engine, sponsor_campaign_id: str, actor: str = "user", **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in plans_t.c}
    fields["updated_at"] = datetime.now()
    with engine.begin() as c:
        exists = c.execute(select(plans_t.c.sponsor_campaign_id).where(
            plans_t.c.sponsor_campaign_id == sponsor_campaign_id)).first()
        if exists:
            c.execute(update(plans_t).where(plans_t.c.sponsor_campaign_id == sponsor_campaign_id).values(**fields))
        else:
            c.execute(insert(plans_t).values(sponsor_campaign_id=sponsor_campaign_id, **fields))
        _log(c, "campaign_plan", f"{sponsor_campaign_id}: {fields}", actor)


def add_task(engine, actor: str = "user", **fields) -> int:
    now = datetime.now()
    fields = {k: v for k, v in fields.items() if k in tasks_t.c and k != "task_id"}
    fields.setdefault("status", "todo")
    fields.setdefault("priority", "medium")
    with engine.begin() as c:
        res = c.execute(insert(tasks_t).values(**fields, created_at=now, updated_at=now))
        tid = int(res.inserted_primary_key[0])
        _log(c, "task_add", f"#{tid} {fields.get('title')}", actor)
    return tid


def update_task(engine, task_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in tasks_t.c and k != "task_id"}
    fields["updated_at"] = datetime.now()
    with engine.begin() as c:
        c.execute(update(tasks_t).where(tasks_t.c.task_id == task_id).values(**fields))
        _log(c, "task_update", f"#{task_id} {fields}")


def delete_task(engine, task_id: int) -> None:
    with engine.begin() as c:
        c.execute(delete(tasks_t).where(tasks_t.c.task_id == task_id))
        _log(c, "task_delete", f"#{task_id}")


def add_cash_receipt(engine, opportunity_id: str, amount_inr: int, received_at: datetime, note: str = "") -> None:
    with engine.begin() as c:
        c.execute(insert(cash_t).values(opportunity_id=opportunity_id, amount_inr=int(amount_inr),
                                        received_at=received_at, note=note))
        _log(c, "cash_receipt", f"{opportunity_id} ₹{amount_inr:,}")


def replace_source_table(engine, name: str, df: pd.DataFrame) -> None:
    """Used by the raw data editor: replace a source table wholesale (validated by caller)."""
    if name not in SOURCE_TABLES:
        raise ValueError(name)
    with engine.begin() as c:
        df.to_sql(name, c, if_exists="replace", index=False)
        _log(c, "table_edit", f"{name}: {len(df)} rows saved")
