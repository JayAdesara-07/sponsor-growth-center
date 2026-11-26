"""
Decision layer on top of sponsor_data: scale / change / stop rules, snapshot comparison,
and metrics that depend on app-entered data (cash receipts, spend). Shared by the
dashboard and the AI copilot so both always say the same thing.
"""
from __future__ import annotations

import pandas as pd

import sponsor_data as sd

# Thresholds (mirrors Slide 3). Kept in one place so the UI can display them.
RULES = {
    "min_brands_for_verdict": 10,       # below this: too early to judge
    "scale_contact_to_confirmed_pct": 25,
    "stop_contacted_min": 30,
    "stop_contact_to_confirmed_pct": 2,
    "stop_meeting_rate_pct": 10,
    "change_stale_share_pct": 50,
    "stale_days": sd.STALE_DAYS,
}


def recommendations(s: sd.Snapshot) -> pd.DataFrame:
    """One row per campaign: verdict (Scale / Change / Stop / Hold / Too early) + reasons + evidence."""
    ct = sd.campaign_table(s)
    stale = sd.stale_opportunities(s)
    stale_by_c = stale.merge(s.opportunities[["opportunity_id", "sponsor_campaign_id"]], on="opportunity_id") \
                      .groupby("sponsor_campaign_id").size()
    rows = []
    R = RULES
    for _, r in ct.iterrows():
        open_n = int(r["opportunities"] - r["confirmed"] - r["lost"])
        n_stale = int(stale_by_c.get(r["sponsor_campaign_id"], 0))
        stale_share = round(100 * n_stale / open_n, 1) if open_n else 0.0
        c2c = r["contact_to_confirmed_pct"] or 0
        meet = r["meeting_rate_pct"] or 0
        reasons = []
        small = r["brands_contacted"] < R["min_brands_for_verdict"]
        if small and not (r["confirmed"] >= 3 and c2c >= R["scale_contact_to_confirmed_pct"]):
            verdict = "Too early"
            reasons.append(f"only {r['brands_contacted']} brands contacted (< {R['min_brands_for_verdict']})")
        elif small:
            verdict = "Scale"
            reasons.append(f"{r['confirmed']} of {r['brands_contacted']} contacted brands confirmed ({c2c}%); "
                           "small sample, so the constraint is lead supply: find more such brands")
        elif c2c >= R["scale_contact_to_confirmed_pct"]:
            verdict = "Scale"
            reasons.append(f"{c2c}% of contacted brands confirmed (≥ {R['scale_contact_to_confirmed_pct']}%)")
            if r["win_rate_pct"] is not None:
                reasons.append(f"win rate on closed deals {r['win_rate_pct']}%")
        elif (r["brands_contacted"] >= R["stop_contacted_min"] and c2c < R["stop_contact_to_confirmed_pct"]
              and meet < R["stop_meeting_rate_pct"]):
            verdict = "Stop"
            reasons.append(f"{r['brands_contacted']} brands contacted, {c2c}% confirmed, meeting rate {meet}% (< {R['stop_meeting_rate_pct']}%)")
            if r["opt_outs"]:
                reasons.append(f"{r['opt_outs']} opt-outs")
        elif open_n and stale_share >= R["change_stale_share_pct"]:
            verdict = "Change"
            reasons.append(f"{n_stale} of {open_n} open deals idle ≥ {R['stale_days']} days ({stale_share}%)")
            if r["confirmed"] == 0:
                reasons.append("interest exists (replies/meetings) but no deal has closed: fix qualification and follow-up")
        else:
            verdict = "Hold"
            reasons.append("no threshold crossed")
        rows.append({
            "sponsor_campaign_id": r["sponsor_campaign_id"], "campaign_name": r["campaign_name"],
            "verdict": verdict, "reasons": "; ".join(reasons),
            "brands_contacted": int(r["brands_contacted"]), "reply_rate_pct": r["reply_rate_pct"],
            "meeting_rate_pct": r["meeting_rate_pct"], "confirmed": int(r["confirmed"]),
            "contact_to_confirmed_pct": r["contact_to_confirmed_pct"], "open_deals": open_n,
            "stale_open_deals": n_stale, "confirmed_value_inr": int(r["confirmed_value_inr"]),
        })
    return pd.DataFrame(rows)


def compare(a: sd.Snapshot, b: sd.Snapshot) -> dict:
    """What changed between two snapshots (a = earlier, b = later)."""
    ha, hb = sd.headline(a), sd.headline(b)
    keys = ["qualified_brands", "confirmed_partnerships", "confirmed_value_inr", "open_opportunities",
            "open_pipeline_value_inr", "lost_or_withdrawn"]
    head = {k: {"from": ha[k], "to": hb[k], "change": hb[k] - ha[k]} for k in keys}
    ca, cb = sd.campaign_table(a).set_index("sponsor_campaign_id"), sd.campaign_table(b).set_index("sponsor_campaign_id")
    cols = ["brands_contacted", "brands_replied", "brands_met", "confirmed", "confirmed_value_inr"]
    delta = (cb[cols] - ca.reindex(cb.index)[cols].fillna(0)).astype(int)
    delta.insert(0, "campaign_name", cb["campaign_name"])
    # deals that changed stage between the two dates
    oa = a.opportunities.set_index("opportunity_id")["stage"]
    ob = b.opportunities.set_index("opportunity_id")[["brand_name", "stage", "sponsor_campaign_id"]]
    ob["stage_before"] = oa.reindex(ob.index).fillna("(not created)")
    moved = ob[ob["stage"] != ob["stage_before"]].reset_index()
    return {"from": a.cutoff.date().isoformat(), "to": b.cutoff.date().isoformat(), "headline": head,
            "by_campaign": delta.reset_index(), "stage_changes": moved}


def cash_summary(s: sd.Snapshot, receipts: pd.DataFrame) -> dict:
    """Cash collected only exists if the team records receipts in the app. The source data has none."""
    conf = s.opportunities[s.opportunities["stage"] == "partner_confirmed"]
    r = receipts.copy()
    if len(r):
        r["received_at"] = pd.to_datetime(r["received_at"])
        r = r[r["received_at"] <= s.cutoff]
    collected = int(r["amount_inr"].sum()) if len(r) else 0
    cash_conf = int(conf.loc[conf["support_type"] == "cash", "confirmed_value_inr"].sum())
    return {
        "receipts_recorded": int(len(r)),
        "cash_collected_inr": collected if len(r) else None,
        "confirmed_cash_type_value_inr": cash_conf,
        "outstanding_inr": cash_conf - collected if len(r) else None,
        "note": ("No cash receipts are recorded: the source data reports partnership value, not bank receipts, "
                 "so cash collected is unknown.") if not len(r) else "Based on receipts recorded in the app.",
    }


def spend_summary(plans: pd.DataFrame, ct: pd.DataFrame) -> pd.DataFrame:
    """Cost per confirmed deal only where the team has entered spend."""
    p = plans[["sponsor_campaign_id", "budget_inr", "spend_inr", "status"]]
    m = ct[["sponsor_campaign_id", "campaign_name", "confirmed", "confirmed_value_inr"]].merge(p, on="sponsor_campaign_id", how="left")
    m["cost_per_confirmed_inr"] = [int(s / c) if pd.notna(s) and c else None for s, c in zip(m["spend_inr"], m["confirmed"])]
    m["value_per_rupee"] = [round(v / s, 1) if pd.notna(s) and s else None for v, s in zip(m["confirmed_value_inr"], m["spend_inr"])]
    return m
