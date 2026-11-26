"""
Sponsor data layer for the RISA Growth APM assignment (Track B: Sponsorship).

One place that turns raw source tables into trustworthy numbers. The dashboard,
the slides and the AI copilot all call these functions, so every surface shows
the same figures and everything recomputes when the underlying data changes.

Source rules implemented (from the dataset's Read me / Field guide):
  1. Import retries: identical rows repeat with the same stable ID -> deduplicate by ID.
  2. Full-state histories (qualification, opportunity stage): use the LATEST version
     with effective_at <= cutoff per entity. Never sum history rows.
  3. Snapshot cutoff = end of the selected day in Asia/Kolkata. Nothing after the
     cutoff may appear (no leakage of later replies, stages or values).
  4. Populations are distinct: outreach attempts != contacts != responding brands
     != qualified brands != confirmed partnerships. Repeat outreach is not a new brand.
  5. A positive reply does not mean qualified; qualified does not mean confirmed.
  6. confirmed_value_inr is a reported partnership value, NOT cash received.
     The source has no payment / bank-receipt data.
  7. Planned campaign dates are plans, not outcomes. Activations are associations,
     not proof of causal uplift.

Timestamps in the workbook are IST wall-clock values (+05:30); they are kept as
naive IST datetimes throughout.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
SHEETS = {
    "event": "Event",
    "targets": "Targets",
    "brands": "Brands",
    "contacts": "Sponsor contacts",
    "campaigns": "Sponsor campaigns",
    "interactions": "Sponsor interactions",
    "qualification": "Brand qualification",
    "opportunities": "Partner opportunities",
    "opp_history": "Opportunity history",
    "activations": "Sponsor activations",
}

ID_COLUMNS = {
    "brands": "brand_id",
    "contacts": "contact_id",
    "campaigns": "sponsor_campaign_id",
    "interactions": "interaction_id",
    "qualification": "history_id",
    "opportunities": "opportunity_id",
    "opp_history": "history_id",
    "activations": "activation_id",
}

DATE_COLUMNS = {
    "event": ["history_start", "history_end", "event_starts_at", "event_ends_at"],
    "targets": ["effective_at"],
    "brands": ["created_at"],
    "contacts": ["created_at"],
    "campaigns": ["planned_start_at", "planned_end_at", "created_at"],
    "interactions": ["occurred_at"],
    "qualification": ["effective_at"],
    "opportunities": ["created_at"],
    "opp_history": ["effective_at"],
    "activations": ["linked_at"],
}

# Opportunity stages in pipeline order. lost / withdrawn are terminal exits.
STAGE_ORDER = ["prospecting", "contacted", "proposal_sent", "negotiating", "partner_confirmed"]
STAGE_RANK = {s: i for i, s in enumerate(STAGE_ORDER)}
OPEN_STAGES = ["prospecting", "contacted", "proposal_sent", "negotiating"]
CLOSED_LOST = ["lost", "withdrawn"]

ROOT_TOUCH_EVENTS = ["outreach_sent", "introduction_received", "web_inbound"]


def load_workbook(path: str | Path) -> dict[str, pd.DataFrame]:
    """Read the source workbook into raw DataFrames (no cleaning)."""
    xl = pd.ExcelFile(path)
    return {key: xl.parse(sheet) for key, sheet in SHEETS.items()}


def clean(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Deduplicate import retries and normalise types. Works for any source
    (Excel, CSV, database) as long as the column names match."""
    out: dict[str, pd.DataFrame] = {}
    for key, df in raw.items():
        df = df.copy()
        for col in DATE_COLUMNS.get(key, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
        id_col = ID_COLUMNS.get(key)
        if id_col and id_col in df.columns:
            df = df.drop_duplicates(subset=id_col, keep="first")
        out[key] = df.reset_index(drop=True)
    for col in ("proposed_value_inr", "confirmed_value_inr"):
        out["opp_history"][col] = pd.to_numeric(out["opp_history"][col], errors="coerce").fillna(0).astype(int)
    return out


def load(path: str | Path) -> dict[str, pd.DataFrame]:
    return clean(load_workbook(path))


# ---------------------------------------------------------------------------
# Snapshots (point-in-time views)
# ---------------------------------------------------------------------------
def cutoff_for(day: date | str | datetime) -> datetime:
    """End of the selected day in IST (inclusive)."""
    d = pd.Timestamp(day).date()
    return datetime.combine(d, time(23, 59, 59, 999999))


def _latest(df: pd.DataFrame, key: str, ts: str, cutoff: datetime) -> pd.DataFrame:
    eligible = df[df[ts] <= cutoff]
    if eligible.empty:
        return eligible
    # history_id breaks ties deterministically if two versions share a timestamp
    sort_cols = [ts] + (["history_id"] if "history_id" in eligible.columns else [])
    return eligible.sort_values(sort_cols).groupby(key, as_index=False).tail(1)


@dataclass
class Snapshot:
    cutoff: datetime
    brands: pd.DataFrame
    contacts: pd.DataFrame
    campaigns: pd.DataFrame
    interactions: pd.DataFrame
    qualification: pd.DataFrame      # latest version per brand
    opportunities: pd.DataFrame      # static opp rows + latest stage/value columns
    opp_history: pd.DataFrame        # all versions <= cutoff (for "ever reached" logic)
    activations: pd.DataFrame
    target: pd.Series | None         # target version in force at cutoff


def snapshot(data: dict[str, pd.DataFrame], day: date | str | datetime | None = None) -> Snapshot:
    """Point-in-time view. day=None -> end of the data's history window."""
    if day is None:
        day = data["event"]["history_end"].iloc[0]
    c = cutoff_for(day)

    brands = data["brands"][data["brands"]["created_at"] <= c]
    contacts = data["contacts"][data["contacts"]["created_at"] <= c]
    inter = data["interactions"][data["interactions"]["occurred_at"] <= c]
    qual = _latest(data["qualification"], "brand_id", "effective_at", c)
    hist = data["opp_history"][data["opp_history"]["effective_at"] <= c]
    latest = _latest(data["opp_history"], "opportunity_id", "effective_at", c)

    opps = data["opportunities"][data["opportunities"]["created_at"] <= c].merge(
        latest[["opportunity_id", "stage", "proposed_value_inr", "confirmed_value_inr",
                "owner_name", "owner_id", "effective_at"]].rename(
            columns={"owner_name": "deal_owner_name", "owner_id": "deal_owner_id",
                     "effective_at": "stage_since"}),
        on="opportunity_id", how="left")
    # opportunity exists but no stage version yet at cutoff
    opps["stage"] = opps["stage"].fillna("prospecting")
    opps[["proposed_value_inr", "confirmed_value_inr"]] = opps[
        ["proposed_value_inr", "confirmed_value_inr"]].fillna(0).astype(int)

    # furthest pipeline stage ever reached (lost after proposal still counts as a proposal)
    reached = (hist[hist["stage"].isin(STAGE_ORDER)]
               .assign(rank=lambda d: d["stage"].map(STAGE_RANK))
               .groupby("opportunity_id")["rank"].max())
    opps["max_stage_rank"] = opps["opportunity_id"].map(reached).fillna(0).astype(int)

    tgt = data["targets"][data["targets"]["effective_at"] <= c].sort_values("effective_at")
    target = tgt.iloc[-1] if not tgt.empty else None

    acts = data["activations"][data["activations"]["linked_at"] <= c]
    return Snapshot(c, brands, contacts, data["campaigns"], inter, qual, opps, hist, acts, target)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def funnel(s: Snapshot) -> pd.DataFrame:
    """Overall sponsor funnel. Brand-level up to qualification, opportunity-level after."""
    i = s.interactions
    touched = i[i["event_type"].isin(ROOT_TOUCH_EVENTS)]["brand_id"].nunique()
    replied = i[i["event_type"] == "replied"]["brand_id"].nunique()
    positive = i[(i["event_type"] == "replied") & (i["outcome"] == "positive")]["brand_id"].nunique()
    met = i[i["event_type"] == "meeting_held"]["brand_id"].nunique()
    qualified = int((s.qualification["qualification_status"] == "qualified").sum())
    o = s.opportunities
    opps = len(o)
    proposals = int((o["max_stage_rank"] >= STAGE_RANK["proposal_sent"]).sum())
    negotiating = int((o["max_stage_rank"] >= STAGE_RANK["negotiating"]).sum())
    confirmed = int((o["stage"] == "partner_confirmed").sum())
    rows = [
        ("Brands in research", "brand", len(s.brands)),
        ("Brands contacted", "brand", touched),
        ("Brands replied", "brand", replied),
        ("Brands replied positively", "brand", positive),
        ("Brands with meeting held", "brand", met),
        ("Brands qualified (current)", "brand", qualified),
        ("Opportunities created", "opportunity", opps),
        ("Opportunities reached proposal", "opportunity", proposals),
        ("Opportunities reached negotiation", "opportunity", negotiating),
        ("Partnerships confirmed (current)", "opportunity", confirmed),
    ]
    df = pd.DataFrame(rows, columns=["stage", "unit", "count"])
    df["conv_from_prev_pct"] = [None] + [_pct(df["count"][k], df["count"][k - 1]) for k in range(1, len(df))]
    df["conv_from_contacted_pct"] = [_pct(v, touched) if k >= 1 else None for k, v in enumerate(df["count"])]
    return df


def headline(s: Snapshot) -> dict:
    """Top-line KPIs and target vs actual."""
    o = s.opportunities
    conf = o[o["stage"] == "partner_confirmed"]
    open_ = o[o["stage"].isin(OPEN_STAGES)]
    qualified = int((s.qualification["qualification_status"] == "qualified").sum())
    t = s.target
    out = {
        "as_of": s.cutoff.date().isoformat(),
        "target_version": None if t is None else t["target_version"],
        "qualified_brands": qualified,
        "qualified_brands_goal": None if t is None else int(t["qualified_brands_goal"]),
        "confirmed_partnerships": len(conf),
        "confirmed_partnerships_goal": None if t is None else int(t["confirmed_partnerships_goal"]),
        "confirmed_value_inr": int(conf["confirmed_value_inr"].sum()),
        "confirmed_cash_value_inr": int(conf.loc[conf["support_type"] == "cash", "confirmed_value_inr"].sum()),
        "confirmed_in_kind_value_inr": int(conf.loc[conf["support_type"] == "in_kind", "confirmed_value_inr"].sum()),
        "avg_confirmed_deal_inr": int(conf["confirmed_value_inr"].mean()) if len(conf) else 0,
        "open_opportunities": len(open_),
        "open_pipeline_value_inr": int(open_["proposed_value_inr"].sum()),
        "lost_or_withdrawn": int(o["stage"].isin(CLOSED_LOST).sum()),
        "cash_collected_inr": None,  # not in source data -- see rule 6
    }
    for k in ("qualified_brands", "confirmed_partnerships"):
        g = out[f"{k}_goal"]
        out[f"{k}_attainment_pct"] = _pct(out[k], g) if g else None
    return out


def campaign_table(s: Snapshot) -> pd.DataFrame:
    """Per-campaign performance.

    Attribution (stated, because the source says campaign association is observational):
      - outreach / reply / meeting columns: brands with that event inside the campaign
        (a brand touched by two campaigns counts in both);
      - qualified: latest qualification version's source campaign;
      - opportunities / confirmed / value: the opportunity's originating campaign.
    """
    i = s.interactions
    c = s.campaigns[["sponsor_campaign_id", "campaign_name", "channel", "owner_name"]].set_index("sponsor_campaign_id")

    def brands_where(mask):
        return i[mask].groupby("sponsor_campaign_id")["brand_id"].nunique()

    c["attempts"] = i[i["event_type"].isin(ROOT_TOUCH_EVENTS)].groupby("sponsor_campaign_id")["attempt_id"].nunique()
    c["brands_contacted"] = brands_where(i["event_type"].isin(ROOT_TOUCH_EVENTS))
    c["brands_replied"] = brands_where(i["event_type"] == "replied")
    c["brands_positive"] = brands_where((i["event_type"] == "replied") & (i["outcome"] == "positive"))
    c["brands_met"] = brands_where(i["event_type"] == "meeting_held")
    c["opt_outs"] = brands_where(i["event_type"] == "opt_out")
    q = s.qualification
    c["brands_qualified"] = q[q["qualification_status"] == "qualified"].groupby("sponsor_campaign_id")["brand_id"].nunique()
    o = s.opportunities
    c["opportunities"] = o.groupby("sponsor_campaign_id")["opportunity_id"].nunique()
    conf = o[o["stage"] == "partner_confirmed"]
    c["confirmed"] = conf.groupby("sponsor_campaign_id")["opportunity_id"].nunique()
    c["confirmed_value_inr"] = conf.groupby("sponsor_campaign_id")["confirmed_value_inr"].sum()
    op = o[o["stage"].isin(OPEN_STAGES)]
    c["open_pipeline_inr"] = op.groupby("sponsor_campaign_id")["proposed_value_inr"].sum()
    c["lost"] = o[o["stage"].isin(CLOSED_LOST)].groupby("sponsor_campaign_id")["opportunity_id"].nunique()
    c = c.fillna(0)
    num = [col for col in c.columns if col not in ("campaign_name", "channel", "owner_name")]
    c[num] = c[num].astype(int)
    c["reply_rate_pct"] = [_pct(a, b) for a, b in zip(c["brands_replied"], c["brands_contacted"])]
    c["meeting_rate_pct"] = [_pct(a, b) for a, b in zip(c["brands_met"], c["brands_contacted"])]
    c["contact_to_confirmed_pct"] = [_pct(a, b) for a, b in zip(c["confirmed"], c["brands_contacted"])]
    c["win_rate_pct"] = [_pct(a, b) for a, b in zip(c["confirmed"], c["confirmed"] + c["lost"])]
    c["avg_deal_inr"] = [int(v / n) if n else 0 for v, n in zip(c["confirmed_value_inr"], c["confirmed"])]
    c["value_per_brand_contacted_inr"] = [int(v / n) if n else 0 for v, n in zip(c["confirmed_value_inr"], c["brands_contacted"])]
    return c.reset_index()


def stage_conversion(s: Snapshot) -> pd.DataFrame:
    """Of opportunities that reached stage X, how many reached the next stage and how many
    were finally confirmed. Uses 'ever reached' from history so later losses are kept."""
    o = s.opportunities
    rows = []
    for st in STAGE_ORDER[:-1]:
        reached = o[o["max_stage_rank"] >= STAGE_RANK[st]]
        nxt = reached[reached["max_stage_rank"] >= STAGE_RANK[st] + 1]
        won = reached[reached["stage"] == "partner_confirmed"]
        resolved = reached[reached["stage"].isin(["partner_confirmed", *CLOSED_LOST])]
        rows.append({
            "stage": st, "reached": len(reached), "reached_next": len(nxt),
            "next_stage_pct": _pct(len(nxt), len(reached)),
            "resolved": len(resolved), "won": len(won),
            "win_rate_of_resolved_pct": _pct(len(won), len(resolved)),
        })
    return pd.DataFrame(rows)


def cycle_times(s: Snapshot) -> pd.DataFrame:
    """Days from opportunity creation to confirmation, and between stages, for confirmed deals."""
    h = s.opp_history
    conf_ids = s.opportunities.loc[s.opportunities["stage"] == "partner_confirmed", "opportunity_id"]
    first = h.groupby(["opportunity_id", "stage"])["effective_at"].min().unstack()
    first = first.loc[first.index.intersection(conf_ids)]
    out = pd.DataFrame(index=first.index)
    created = s.opportunities.set_index("opportunity_id")["created_at"]
    out["days_create_to_confirm"] = (first["partner_confirmed"] - created.reindex(first.index)).dt.days
    out["days_proposal_to_confirm"] = (first["partner_confirmed"] - first.get("proposal_sent")).dt.days
    return out.reset_index()


def first_touch_to_meeting_days(s: Snapshot) -> pd.Series:
    i = s.interactions
    first_touch = i[i["event_type"].isin(ROOT_TOUCH_EVENTS)].groupby("brand_id")["occurred_at"].min()
    first_meet = i[i["event_type"] == "meeting_held"].groupby("brand_id")["occurred_at"].min()
    return (first_meet - first_touch.reindex(first_meet.index)).dt.days


def owner_table(s: Snapshot) -> pd.DataFrame:
    o = s.opportunities
    g = o.groupby("deal_owner_name")
    df = pd.DataFrame({
        "opportunities": g.size(),
        "confirmed": g.apply(lambda d: (d["stage"] == "partner_confirmed").sum()),
        "open": g.apply(lambda d: d["stage"].isin(OPEN_STAGES).sum()),
        "lost": g.apply(lambda d: d["stage"].isin(CLOSED_LOST).sum()),
        "confirmed_value_inr": g.apply(lambda d: d.loc[d["stage"] == "partner_confirmed", "confirmed_value_inr"].sum()),
        "open_pipeline_inr": g.apply(lambda d: d.loc[d["stage"].isin(OPEN_STAGES), "proposed_value_inr"].sum()),
    })
    return df.astype(int).reset_index().rename(columns={"deal_owner_name": "owner"})


def industry_table(s: Snapshot) -> pd.DataFrame:
    b = s.brands[["brand_id", "industry"]]
    q = s.qualification.merge(b, on="brand_id")
    o = s.opportunities.merge(b, on="brand_id")
    conf = o[o["stage"] == "partner_confirmed"]
    df = pd.DataFrame({
        "brands": b.groupby("industry").size(),
        "qualified": q[q["qualification_status"] == "qualified"].groupby("industry").size(),
        "confirmed": conf.groupby("industry").size(),
        "confirmed_value_inr": conf.groupby("industry")["confirmed_value_inr"].sum(),
    }).fillna(0).astype(int)
    df["qualify_rate_pct"] = [_pct(a, b) for a, b in zip(df["qualified"], df["brands"])]
    df["avg_deal_inr"] = [int(v / n) if n else 0 for v, n in zip(df["confirmed_value_inr"], df["confirmed"])]
    return df.reset_index()


def weekly_trend(s: Snapshot) -> pd.DataFrame:
    """Weekly counts of outreach, replies, meetings and confirmations (actual event dates)."""
    i = s.interactions.copy()
    i["week"] = i["occurred_at"].dt.to_period("W-SUN").dt.start_time
    piv = i.pivot_table(index="week", columns="event_type", values="interaction_id",
                        aggfunc="count", fill_value=0)
    h = s.opp_history[s.opp_history["stage"] == "partner_confirmed"].copy()
    h = h.sort_values("effective_at").groupby("opportunity_id").head(1)
    h["week"] = h["effective_at"].dt.to_period("W-SUN").dt.start_time
    piv["confirmations"] = h.groupby("week").size()
    piv["confirmed_value_inr"] = h.groupby("week")["confirmed_value_inr"].sum()
    return piv.fillna(0).astype(int).reset_index()


STALE_DAYS = 7          # in CampusFest no won deal sat >5 days in a stage; 0 of 26 deals idle >=7 days closed
STALE_PROB_FACTOR = 0.1  # stale deals keep 10% of their win probability (not 0: small sample)


def stale_opportunities(s: Snapshot, days: int = STALE_DAYS) -> pd.DataFrame:
    """Open opportunities whose stage has not changed for `days` or more at the cutoff."""
    o = s.opportunities
    open_ = o[o["stage"].isin(OPEN_STAGES)].copy()
    open_["days_in_stage"] = (pd.Timestamp(s.cutoff) - open_["stage_since"]).dt.days
    cols = ["opportunity_id", "opportunity_name", "brand_name", "originating_campaign_name",
            "stage", "proposed_value_inr", "deal_owner_name", "stage_since", "days_in_stage"]
    return open_[open_["days_in_stage"] >= days][cols].sort_values("days_in_stage", ascending=False)


def weighted_forecast(s: Snapshot, event_start: datetime | None = None, prior_strength: float = 3.0) -> dict:
    """Projected confirmed partnerships/value at the cutoff.

    Each open opportunity's win probability = its originating campaign's win rate on resolved
    deals, shrunk toward the overall win rate from its current stage (Beta-style smoothing with
    `prior_strength` pseudo-deals) so a campaign with 2 resolved deals does not get 0% or 100%.
    If the cutoff is on/after the event start, no further deals can be confirmed *before the
    festival*, so open pipeline contributes 0 and is reported as unrealised.
    """
    o = s.opportunities
    sc = stage_conversion(s).set_index("stage")
    open_ = o[o["stage"].isin(OPEN_STAGES)].copy()
    resolved = o[o["stage"].isin(["partner_confirmed", *CLOSED_LOST])]
    won_by_c = resolved[resolved["stage"] == "partner_confirmed"].groupby("sponsor_campaign_id").size()
    res_by_c = resolved.groupby("sponsor_campaign_id").size()

    def prob(row):
        p_stage = (sc.loc[row["stage"], "win_rate_of_resolved_pct"] or 0) / 100
        w = won_by_c.get(row["sponsor_campaign_id"], 0)
        n = res_by_c.get(row["sponsor_campaign_id"], 0)
        return (w + prior_strength * p_stage) / (n + prior_strength)

    open_["win_prob"] = open_.apply(prob, axis=1) if len(open_) else []
    open_["days_in_stage"] = (pd.Timestamp(s.cutoff) - open_["stage_since"]).dt.days
    open_["stale"] = open_["days_in_stage"] >= STALE_DAYS
    open_.loc[open_["stale"], "win_prob"] *= STALE_PROB_FACTOR
    event_started = event_start is not None and s.cutoff >= event_start
    if event_started:
        open_["win_prob"] = 0.0
    open_["expected_inr"] = open_["proposed_value_inr"] * open_["win_prob"]
    confirmed_n = int((o["stage"] == "partner_confirmed").sum())
    confirmed_value = int(o.loc[o["stage"] == "partner_confirmed", "confirmed_value_inr"].sum())
    return {
        "confirmed_partnerships": confirmed_n,
        "confirmed_value_inr": confirmed_value,
        "open_opportunities": len(open_),
        "open_pipeline_inr": int(open_["proposed_value_inr"].sum()),
        "open_expected_inr": int(open_["expected_inr"].sum()),
        "projected_partnerships": round(confirmed_n + float(open_["win_prob"].sum()), 1),
        "projected_value_inr": confirmed_value + int(open_["expected_inr"].sum()),
        "event_started": event_started,
        "by_opportunity": open_[["opportunity_id", "brand_name", "sponsor_campaign_id", "stage",
                                 "proposed_value_inr", "days_in_stage", "stale", "win_prob", "expected_inr"]],
        "method": ("campaign win rate on resolved deals, smoothed toward stage win rate "
                   f"(prior strength {prior_strength}); x{STALE_PROB_FACTOR} if idle >= {STALE_DAYS} days "
                   "in stage; 0 after event start"),
    }
