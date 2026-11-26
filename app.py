"""
Sponsor Growth Center: analytics dashboard, campaign & task management, embedded AI copilot.
Run:  streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import copilot as cp
import insights as ins
import sponsor_data as sd
import store

st.set_page_config(page_title="Sponsor Growth Center", page_icon="📈", layout="wide")

# Palette (dataviz reference categorical slots 1-3 + neutrals)
C1, C2, C3 = "#257de0", "#f47230", "#00b894"
INK, MUTED, GRID = "#191919", "#666666", "#e6e6e6"
VERDICT_ICON = {"Scale": "🟢 Scale", "Change": "🟠 Change", "Stop": "🔴 Stop", "Hold": "⚪ Hold", "Too early": "⚪ Too early"}


def secret(name, default=None):
    try:
        return st.secrets.get(name, os.environ.get(name, default))
    except Exception:  # noqa: BLE001 - no secrets file
        return os.environ.get(name, default)


@st.cache_resource
def engine():
    url = secret("DATABASE_URL")
    e = store.get_engine(url)
    store.seed(e)
    return e


def inr(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    v = float(v)
    if abs(v) >= 1e7:
        return f"₹{v/1e7:.2f} Cr"
    if abs(v) >= 1e5:
        return f"₹{v/1e5:.1f}L"
    return f"₹{v:,.0f}"


def style_fig(fig, height=320):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="white",
                      paper_bgcolor="white", font=dict(color=INK, size=13),
                      legend=dict(orientation="h", y=1.12, x=0), hoverlabel=dict(bgcolor="white"))
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


E = engine()


@st.cache_data(show_spinner=False, max_entries=4)
def cached_source(version: int):
    return store.load_source(engine())


@st.cache_data(show_spinner=False, max_entries=32)
def cached_app_table(name: str, version: int):
    return store.load_app_table(engine(), name)


VERSION = store.data_version(E)
data = cached_source(VERSION)
end_day = store.data_end(data, E)
start_day = data["event"]["history_start"].iloc[0].date()
event_start = data["event"]["event_starts_at"].iloc[0]

# ---------------------------------------------------------------------------
# Sidebar
with st.sidebar:
    st.markdown("### 📈 Sponsor Growth Center")
    st.caption(f"{data['event']['event_name'].iloc[0]} · event {event_start:%d %b %Y} · synthetic data")
    as_of = st.date_input("Snapshot as of (end of day, IST)", value=end_day, min_value=start_day,
                          max_value=max(end_day, start_day), help="Every number, chart and copilot answer uses this date. "
                          "Nothing that happened after it is shown.")
    S = sd.snapshot(data, as_of)
    tgt = S.target
    st.caption(f"Targets in force: **{tgt['target_version'] if tgt is not None else '—'}**")
    db_kind = "Postgres (Supabase)" if E.dialect.name == "postgresql" else "SQLite (local)"
    st.caption(f"Database: {db_kind}")
    st.divider()
    with st.expander("Reset demo data"):
        st.write("Restores the original dataset and clears tasks, plans and cash receipts you added.")
        if st.checkbox("I understand this discards my changes"):
            if st.button("Reset to original data", type="primary"):
                store.seed(E, reset=True)
                st.cache_data.clear()
                st.session_state.pop("chat", None)
                st.rerun()

H = sd.headline(S)
F = sd.weighted_forecast(S, event_start)
receipts = cached_app_table("cash_receipts", VERSION)
plans = cached_app_table("campaign_plans", VERSION)
tasks = cached_app_table("tasks", VERSION)
CASH = ins.cash_summary(S, receipts)
REC = ins.recommendations(S)
CT = sd.campaign_table(S)
camp_names = dict(zip(data["campaigns"]["sponsor_campaign_id"], data["campaigns"]["campaign_name"]))
OWNERS = store.owners(data)

tab_over, tab_camp, tab_pipe, tab_tasks, tab_ai, tab_data = st.tabs(
    ["Overview", "Campaigns & decisions", "Pipeline", "Tasks", "AI copilot", "Data"])

# ---------------------------------------------------------------------------
with tab_over:
    st.subheader(f"Where we stand on {as_of:%d %b %Y}")
    k = st.columns(6)
    g = H["confirmed_partnerships_goal"]
    k[0].metric("Confirmed partnerships", f"{H['confirmed_partnerships']}" + (f" / {g}" if g else ""),
                f"{H['confirmed_partnerships_attainment_pct']}% of goal" if g else None, delta_color="off", delta_arrow="off")
    gq = H["qualified_brands_goal"]
    k[1].metric("Qualified brands", f"{H['qualified_brands']}" + (f" / {gq}" if gq else ""),
                f"{H['qualified_brands_attainment_pct']}% of goal" if gq else None, delta_color="off", delta_arrow="off")
    k[2].metric("Confirmed value (reported)", inr(H["confirmed_value_inr"]),
                f"avg deal {inr(H['avg_confirmed_deal_inr'])}", delta_color="off", delta_arrow="off")
    k[3].metric("Open pipeline", inr(H["open_pipeline_value_inr"]), f"{H['open_opportunities']} open deals", delta_color="off", delta_arrow="off")
    k[4].metric("Projected partnerships", f"{F['projected_partnerships']}", f"{inr(F['projected_value_inr'])} projected",
                delta_color="off", delta_arrow="off", help=F["method"])
    k[5].metric("Cash collected", inr(CASH["cash_collected_inr"]) if CASH["cash_collected_inr"] is not None else "—",
                f"{CASH['receipts_recorded']} receipts recorded" if CASH["receipts_recorded"] else "no receipts recorded",
                delta_color="off", delta_arrow="off", help=CASH["note"])
    if g and F["projected_partnerships"] < g:
        gap = g - H["confirmed_partnerships"]
        st.warning(f"Projected {F['projected_partnerships']} partnerships vs goal {g}: {gap} more confirmations needed. "
                   + ("The event has started, so open deals can no longer close before the festival." if F["event_started"]
                      else f"{len(sd.stale_opportunities(S))} open deals are stale (idle ≥ {sd.STALE_DAYS} days)."))

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Sponsor funnel**")
        fn = sd.funnel(S)
        fig = go.Figure(go.Funnel(y=fn["stage"], x=fn["count"], marker=dict(color=C1),
                                  textinfo="value", hovertemplate="%{y}: %{x}<extra></extra>"))
        st.plotly_chart(style_fig(fig, 380), width="stretch")
        st.caption("Brand-level up to qualification, opportunity-level after. Proposal/negotiation = ever reached.")
    with c2:
        st.markdown("**Confirmed partnerships over time vs goal**")
        conf = S.opp_history[S.opp_history["stage"] == "partner_confirmed"].sort_values("effective_at") \
            .groupby("opportunity_id").head(1)
        # net confirmed count at each day (handles later withdrawals) via daily snapshots
        days = pd.date_range(start_day, as_of, freq="D")
        series = []
        hist = data["opp_history"]
        for d in days[::2] if len(days) > 60 else days:
            c = sd.cutoff_for(d.date())
            lat = hist[hist["effective_at"] <= c].sort_values("effective_at").groupby("opportunity_id").tail(1)
            series.append((d, int((lat["stage"] == "partner_confirmed").sum())))
        ser = pd.DataFrame(series, columns=["day", "confirmed"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ser["day"], y=ser["confirmed"], mode="lines", name="Confirmed (net)",
                                 line=dict(color=C1, width=2), hovertemplate="%{x|%d %b}: %{y}<extra></extra>"))
        tg = data["targets"].sort_values("effective_at")
        for i, r in tg.iterrows():
            x0 = max(r["effective_at"], pd.Timestamp(start_day))
            nxt = tg[tg["effective_at"] > r["effective_at"]]["effective_at"]
            x1 = nxt.iloc[0] if len(nxt) else pd.Timestamp(as_of)
            if x0 <= pd.Timestamp(as_of):
                fig.add_trace(go.Scatter(x=[x0, min(x1, pd.Timestamp(as_of))], y=[r["confirmed_partnerships_goal"]] * 2,
                                         mode="lines", name=f"Goal ({r['target_version']})",
                                         line=dict(color=MUTED, width=2, dash="dash"),
                                         hovertemplate=f"Goal: {r['confirmed_partnerships_goal']}<extra></extra>"))
        fig.add_vline(x=event_start, line=dict(color=C2, width=1, dash="dot"))
        st.plotly_chart(style_fig(fig, 380), width="stretch")

    st.markdown("**Weekly activity**")
    wt = sd.weekly_trend(S)
    fig = go.Figure()
    for col, name, color in [("outreach_sent", "Outreach sent", C1), ("replied", "Replies", C2), ("meeting_held", "Meetings held", C3)]:
        if col in wt:
            fig.add_trace(go.Scatter(x=wt["week"], y=wt[col], name=name, mode="lines+markers",
                                     line=dict(color=color, width=2), marker=dict(size=8)))
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(style_fig(fig, 300), width="stretch")
    with st.expander("Table view: funnel and weekly activity"):
        st.dataframe(fn, hide_index=True, width="stretch")
        st.dataframe(wt, hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
with tab_camp:
    st.subheader("Which campaigns to scale, change or stop")
    rec = REC.copy()
    rec["verdict"] = rec["verdict"].map(VERDICT_ICON)
    pl = plans.set_index("sponsor_campaign_id")
    rec["team status"] = rec["sponsor_campaign_id"].map(pl["status"]).fillna("active")
    st.dataframe(rec[["campaign_name", "verdict", "reasons", "team status", "brands_contacted", "reply_rate_pct",
                      "meeting_rate_pct", "confirmed", "contact_to_confirmed_pct", "open_deals", "stale_open_deals",
                      "confirmed_value_inr"]],
                 hide_index=True, width="stretch",
                 column_config={"reasons": st.column_config.TextColumn(width="large"),
                                "confirmed_value_inr": st.column_config.NumberColumn("confirmed ₹", format="%d")})
    R = ins.RULES
    st.caption(f"Rules: Scale if ≥{R['scale_contact_to_confirmed_pct']}% of contacted brands confirm · "
               f"Stop if ≥{R['stop_contacted_min']} contacted, <{R['stop_contact_to_confirmed_pct']}% confirmed and "
               f"<{R['stop_meeting_rate_pct']}% meeting rate · Change if ≥{R['change_stale_share_pct']}% of open deals idle "
               f"≥{R['stale_days']} days · fewer than {R['min_brands_for_verdict']} brands = too early. "
               "Attribution is observational, not causal.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Brands contacted vs partnerships confirmed**")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=CT["campaign_name"], y=CT["brands_contacted"], name="Brands contacted", marker_color=C1))
        fig.add_trace(go.Bar(x=CT["campaign_name"], y=CT["confirmed"], name="Confirmed", marker_color=C2))
        fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)
        st.plotly_chart(style_fig(fig, 340), width="stretch")
    with c2:
        st.markdown("**Confirmed value and open pipeline by campaign**")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=CT["campaign_name"], y=CT["confirmed_value_inr"], name="Confirmed ₹", marker_color=C1))
        fig.add_trace(go.Bar(x=CT["campaign_name"], y=CT["open_pipeline_inr"], name="Open pipeline ₹", marker_color=C3))
        fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)
        st.plotly_chart(style_fig(fig, 340), width="stretch")

    with st.expander("Full campaign metrics"):
        st.dataframe(CT, hide_index=True, width="stretch")

    st.markdown("#### Campaign plans: status, budget and spend")
    st.caption("The source data has no spend. Enter budget/spend here to unlock cost per confirmed deal.")
    pe = plans.merge(data["campaigns"][["sponsor_campaign_id", "campaign_name", "owner_name"]], on="sponsor_campaign_id", how="left")
    pe = pe[["sponsor_campaign_id", "campaign_name", "owner_name", "status", "budget_inr", "spend_inr",
             "target_confirmed", "target_value_inr", "notes"]]
    edited = st.data_editor(pe, hide_index=True, width="stretch", key="plans_editor",
                            disabled=["sponsor_campaign_id", "campaign_name", "owner_name"],
                            column_config={"status": st.column_config.SelectboxColumn(options=["active", "scale", "change", "stop"])})
    if st.button("Save campaign plans"):
        for _, r in edited.iterrows():
            store.save_plan(E, r["sponsor_campaign_id"], status=r["status"],
                            budget_inr=None if pd.isna(r["budget_inr"]) else int(r["budget_inr"]),
                            spend_inr=None if pd.isna(r["spend_inr"]) else int(r["spend_inr"]),
                            target_confirmed=None if pd.isna(r["target_confirmed"]) else int(r["target_confirmed"]),
                            target_value_inr=None if pd.isna(r["target_value_inr"]) else int(r["target_value_inr"]),
                            notes=r["notes"])
        st.success("Saved.")
        st.rerun()
    sp = ins.spend_summary(plans, CT)
    if sp["spend_inr"].notna().any():
        st.dataframe(sp, hide_index=True, width="stretch")

    with st.expander("➕ Add a campaign"):
        with st.form("new_campaign"):
            n1, n2 = st.columns(2)
            name = n1.text_input("Campaign name")
            channel = n2.selectbox("Channel", ["email", "linkedin", "introduction", "web_inbound", "event", "other"])
            objective = st.text_input("Objective")
            audience = st.text_input("Audience")
            owner = st.selectbox("Owner", OWNERS)
            d1, d2 = st.columns(2)
            ps = d1.date_input("Planned start", value=as_of)
            pe_ = d2.date_input("Planned end", value=as_of + timedelta(days=30))
            if st.form_submit_button("Create campaign") and name:
                cid = store.add_campaign(E, name, channel, objective, audience, owner, store.owner_id_for(data, owner),
                                         datetime.combine(ps, time(9)), datetime.combine(pe_, time(18)))
                st.success(f"Created {cid}.")
                st.rerun()

# ---------------------------------------------------------------------------
with tab_pipe:
    st.subheader("Deal pipeline")
    o = S.opportunities.copy()
    o["days_in_stage"] = (pd.Timestamp(S.cutoff) - o["stage_since"]).dt.days
    o["stale"] = o["stage"].isin(sd.OPEN_STAGES) & (o["days_in_stage"] >= sd.STALE_DAYS)
    f1, f2, f3, f4 = st.columns(4)
    fs = f1.multiselect("Stage", sd.STAGE_ORDER + sd.CLOSED_LOST)
    fc = f2.multiselect("Campaign", sorted(o["originating_campaign_name"].dropna().unique()))
    fo = f3.multiselect("Owner", sorted(o["deal_owner_name"].dropna().unique()))
    only_stale = f4.checkbox(f"Only stale (idle ≥ {sd.STALE_DAYS} days)")
    v = o
    if fs: v = v[v["stage"].isin(fs)]
    if fc: v = v[v["originating_campaign_name"].isin(fc)]
    if fo: v = v[v["deal_owner_name"].isin(fo)]
    if only_stale: v = v[v["stale"]]
    sc = v["stage"].value_counts().reindex(sd.STAGE_ORDER + sd.CLOSED_LOST).fillna(0).astype(int)
    m = st.columns(len(sc))
    for i, (stg, n) in enumerate(sc.items()):
        m[i].metric(stg.replace("_", " "), n)
    st.dataframe(v[["opportunity_id", "brand_name", "originating_campaign_name", "support_type", "stage",
                    "proposed_value_inr", "confirmed_value_inr", "deal_owner_name", "stage_since", "days_in_stage", "stale"]]
                 .sort_values(["stale", "days_in_stage"], ascending=False),
                 hide_index=True, width="stretch",
                 column_config={"stale": st.column_config.CheckboxColumn("stale ⚠"),
                                "stage_since": st.column_config.DatetimeColumn(format="DD MMM YYYY")})

    stale_df = sd.stale_opportunities(S)
    if len(stale_df):
        existing = set(tasks.loc[tasks["status"] != "done", "opportunity_id"].dropna())
        todo = stale_df[~stale_df["opportunity_id"].isin(existing)]
        st.info(f"{len(stale_df)} open deals are idle ≥ {sd.STALE_DAYS} days; {len(todo)} have no open follow-up task. "
                "In this dataset no deal idle 7+ days ever closed.")
        if len(todo) and st.button(f"Create {len(todo)} follow-up tasks (escalate or close)"):
            for _, r in todo.iterrows():
                store.add_task(E, title=f"Escalate or close: {r['brand_name']} ({r['stage'].replace('_', ' ')}, {r['days_in_stage']}d idle)",
                               owner=r["deal_owner_name"], due_date=as_of + timedelta(days=2), priority="high",
                               opportunity_id=r["opportunity_id"],
                               sponsor_campaign_id=o.set_index("opportunity_id").loc[r["opportunity_id"], "sponsor_campaign_id"],
                               description=f"Idle since {r['stage_since']:%d %b}. Rule: escalate at 7 days, close or move to nurture at 14.",
                               source="rule")
            st.success("Tasks created. See the Tasks tab.")
            st.rerun()

    st.markdown("#### Update records")
    a1, a2 = st.columns(2)
    with a1:
        with st.form("stage_form"):
            st.markdown("**Move a deal to a new stage**")
            opts = o.sort_values("brand_name")
            sel = st.selectbox("Opportunity", opts["opportunity_id"],
                               format_func=lambda x: f"{opts.set_index('opportunity_id').loc[x, 'opportunity_name']} · "
                                                     f"{opts.set_index('opportunity_id').loc[x, 'stage']}")
            cur = opts.set_index("opportunity_id").loc[sel]
            new_stage = st.selectbox("New stage", sd.STAGE_ORDER + sd.CLOSED_LOST,
                                     index=(sd.STAGE_ORDER + sd.CLOSED_LOST).index(cur["stage"]))
            val = st.number_input("Proposed value ₹ (becomes confirmed value if partner_confirmed)",
                                  value=int(cur["proposed_value_inr"]), step=5000, min_value=0)
            own = st.selectbox("Deal owner", OWNERS, index=OWNERS.index(cur["deal_owner_name"]) if cur["deal_owner_name"] in OWNERS else 0)
            eff_default = store.suggest_effective_at(data, as_of, "opportunity_id", sel, "opp_history")
            ed = st.date_input("Effective date", value=eff_default.date())
            if st.form_submit_button("Save stage change"):
                eff = datetime.combine(ed, eff_default.time()) if ed == eff_default.date() else datetime.combine(ed, time(18))
                store.set_opportunity_stage(E, data, sel, new_stage, int(val), own, eff)
                if eff.date() > as_of:
                    st.info("Saved with a date after the current snapshot: move the snapshot date forward to see it.")
                st.success("Saved as a new history version.")
                st.rerun()
    with a2:
        with st.form("cash_form"):
            st.markdown("**Record cash received**")
            confd = o[o["stage"] == "partner_confirmed"]
            if len(confd):
                cs = st.selectbox("Confirmed deal", confd["opportunity_id"],
                                  format_func=lambda x: f"{confd.set_index('opportunity_id').loc[x, 'brand_name']} · "
                                                        f"{inr(confd.set_index('opportunity_id').loc[x, 'confirmed_value_inr'])}")
                amt = st.number_input("Amount received ₹", min_value=0, step=5000)
                rd = st.date_input("Received on", value=as_of)
                note = st.text_input("Note (invoice / UTR)")
                if st.form_submit_button("Save receipt") and amt > 0:
                    store.add_cash_receipt(E, cs, int(amt), datetime.combine(rd, time(12)), note)
                    st.success("Receipt saved.")
                    st.rerun()
            else:
                st.caption("No confirmed deals at this date.")
                st.form_submit_button("Save receipt", disabled=True)
    b1, b2 = st.columns(2)
    with b1:
        with st.expander("➕ New opportunity"):
            with st.form("new_opp"):
                brands = data["brands"].sort_values("brand_name")
                bsel = st.selectbox("Brand", brands["brand_id"],
                                    format_func=lambda x: brands.set_index("brand_id").loc[x, "brand_name"])
                csel = st.selectbox("Originating campaign", list(camp_names), format_func=lambda x: camp_names[x])
                stype = st.selectbox("Support type", ["cash", "in_kind"])
                pv = st.number_input("Proposed value ₹", min_value=0, step=5000, value=75000)
                ow = st.selectbox("Owner", OWNERS, key="newopp_owner")
                q = S.qualification.set_index("brand_id")["qualification_status"].get(bsel, "unreviewed")
                st.caption(f"Brand qualification on {as_of:%d %b}: **{q}**"
                           + (" — rule: qualify before opening a deal." if q != "qualified" else ""))
                if st.form_submit_button("Create opportunity"):
                    oid = store.add_opportunity(E, data, bsel, csel, stype, int(pv), ow, datetime.combine(as_of, time(10)))
                    st.success(f"Created {oid}.")
                    st.rerun()
    with b2:
        with st.expander("✔️ Update brand qualification"):
            with st.form("qual"):
                brands = data["brands"].sort_values("brand_name")
                bq = st.selectbox("Brand", brands["brand_id"], key="qb",
                                  format_func=lambda x: brands.set_index("brand_id").loc[x, "brand_name"])
                stq = st.selectbox("Status", ["unreviewed", "engaged", "qualified", "unqualified", "dormant"])
                why = st.text_input("Reason", "Fit confirmed in discovery call")
                if st.form_submit_button("Save qualification"):
                    eff = store.suggest_effective_at(data, as_of, "brand_id", bq, "qualification")
                    store.set_qualification(E, data, bq, stq, why, eff)
                    st.success("Saved as a new qualification version.")
                    st.rerun()

# ---------------------------------------------------------------------------
with tab_tasks:
    st.subheader("Tasks and action items")
    t = tasks.copy()
    t["due_date"] = pd.to_datetime(t["due_date"]).dt.date
    open_t = t[t["status"] != "done"]
    overdue = open_t[open_t["due_date"].notna() & (open_t["due_date"] < as_of)]
    m = st.columns(4)
    m[0].metric("Open tasks", len(open_t))
    m[1].metric(f"Overdue at {as_of:%d %b}", len(overdue))
    m[2].metric("High priority open", int((open_t["priority"] == "high").sum()))
    m[3].metric("Created by copilot", int((t["source"] == "copilot").sum()))
    fo = st.multiselect("Filter by owner", sorted(t["owner"].dropna().unique()), key="task_owner_filter")
    view = t if not fo else t[t["owner"].isin(fo)]
    cols = ["task_id", "title", "owner", "due_date", "status", "priority", "sponsor_campaign_id", "opportunity_id",
            "description", "source"]
    ed = st.data_editor(view[cols].sort_values(["status", "due_date"]), num_rows="dynamic", hide_index=True,
                        width="stretch", key="task_editor", disabled=["task_id", "source"],
                        column_config={
                            "status": st.column_config.SelectboxColumn(options=["todo", "in_progress", "blocked", "done"], required=True),
                            "priority": st.column_config.SelectboxColumn(options=["high", "medium", "low"], required=True),
                            "owner": st.column_config.SelectboxColumn(options=OWNERS),
                            "sponsor_campaign_id": st.column_config.SelectboxColumn("campaign", options=list(camp_names)),
                            "due_date": st.column_config.DateColumn(format="DD MMM YYYY"),
                            "title": st.column_config.TextColumn(required=True, width="large")})
    if st.button("Save task changes", type="primary"):
        before = view.set_index("task_id")
        keep_ids = set(ed["task_id"].dropna().astype(int))
        for tid in set(before.index) - keep_ids:
            store.delete_task(E, int(tid))
        n_new = n_upd = 0
        for _, r in ed.iterrows():
            fields = {c: (None if (not isinstance(r[c], str) and pd.isna(r[c])) else r[c]) for c in cols if c not in ("task_id", "source")}
            if pd.isna(r["task_id"]):
                if fields.get("title"):
                    fields.setdefault("status", "todo")
                    store.add_task(E, **{k: v for k, v in fields.items() if v is not None}, source="manual")
                    n_new += 1
            else:
                old = before.loc[int(r["task_id"])]
                if any(str(old[c]) != str(fields[c]) for c in fields if not (pd.isna(old[c]) and fields[c] is None)):
                    store.update_task(E, int(r["task_id"]), **fields)
                    n_upd += 1
        st.success(f"Saved: {n_new} added, {n_upd} updated, {len(set(before.index) - keep_ids)} deleted.")
        st.rerun()
    st.caption("Add a row at the bottom to create a task; select rows and press Delete to remove. "
               "Changes are written to the database when you press Save.")

# ---------------------------------------------------------------------------
with tab_ai:
    st.subheader("AI growth analyst & copilot")
    key = secret("GEMINI_API_KEY")
    model = secret("GEMINI_MODEL", "gemini-3.8-flash")
    fallbacks = [m.strip() for m in str(secret("GEMINI_FALLBACK_MODELS", "gemini-3.8-flash-lite,gemini-3-flash")).split(",")]
    st.caption(f"Answers come from tools that query the live database at the snapshot date ({as_of:%d %b %Y}). "
               f"Model: {model}. Proposed tasks and status changes are saved only after you confirm.")
    if "chat" not in st.session_state:
        st.session_state.chat = {"history": [], "messages": [], "tools": cp.CopilotTools(E, as_of)}
    chat = st.session_state.chat
    tools = chat["tools"]
    tools.engine, tools.default_as_of = E, as_of
    tools.loader = lambda: cached_source(store.data_version(E))
    tools.app_loader = lambda name: cached_app_table(name, store.data_version(E))

    if not key:
        st.error("No GEMINI_API_KEY configured. Add it to Streamlit secrets to enable the copilot.")
    examples = ["Which campaigns should we scale, change or stop, and why?",
                "Why did we miss the partnership target? What would have closed the gap?",
                "Which deals are stuck and who owns them? Create follow-up tasks.",
                "How much cash have we actually collected?",
                "What changed between 1 March and 15 March?"]
    ex_cols = st.columns(len(examples))
    clicked = None
    for i, q in enumerate(examples):
        if ex_cols[i].button(q, key=f"ex{i}", width="stretch"):
            clicked = q

    for msg in chat["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("trace"):
                with st.expander(f"Data used ({len(msg['trace'])} tool calls)"):
                    for tr in msg["trace"]:
                        st.code(f"{tr['tool']}({tr['args']})\n→ {tr['result_preview']}", language="text")

    # pending proposals
    for p in list(tools.pending):
        f = p["fields"]
        with st.container(border=True):
            if p["kind"] == "task":
                st.markdown(f"**Proposed task:** {f['title']}  \nOwner: {f.get('owner') or '—'} · Due: {f.get('due_date') or '—'} · "
                            f"Priority: {f.get('priority')} · Campaign: {f.get('sponsor_campaign_id') or '—'} · Deal: {f.get('opportunity_id') or '—'}"
                            + (f"  \n{f['description']}" if f.get("description") else ""))
            else:
                st.markdown(f"**Proposed campaign status:** {f['sponsor_campaign_id']} ({camp_names.get(f['sponsor_campaign_id'], '?')}) "
                            f"→ **{f['status']}**  \nReason: {f['notes']}")
            b1, b2, _ = st.columns([1, 1, 6])
            if b1.button("Confirm", key=f"ok{p['proposal_id']}", type="primary"):
                msg = cp.apply_proposal(E, p)
                tools.pending.remove(p)
                chat["messages"].append({"role": "assistant", "content": f"✅ {msg} (confirmed by you)."})
                st.rerun()
            if b2.button("Discard", key=f"no{p['proposal_id']}"):
                tools.pending.remove(p)
                chat["messages"].append({"role": "assistant", "content": f"Discarded proposal: {f.get('title', f.get('status'))}."})
                st.rerun()

    prompt = st.chat_input("Ask about performance, bottlenecks, what to do next…", disabled=not key) or clicked
    if prompt and key:
        chat["messages"].append({"role": "user", "content": prompt})
        try:
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=key, http_options=gtypes.HttpOptions(timeout=90_000))
            sys_p = cp.system_prompt(as_of, OWNERS, data["campaigns"])
            with st.status("Analysing the data…", expanded=True) as status:
                answer, chat["history"], trace = cp.run_turn(client, model, tools, chat["history"], prompt, sys_p,
                                                             on_step=status.write, fallback_models=fallbacks)
                status.update(label=f"Done: {len(trace)} data look-ups", state="complete", expanded=False)
            chat["messages"].append({"role": "assistant", "content": answer, "trace": trace})
        except Exception as e:  # noqa: BLE001
            busy = any(t.lower() in str(e).lower() for t in cp.TRANSIENT)
            hint = (" Google's model is overloaded right now (temporary). Please try again in a minute."
                    if busy else "")
            chat["messages"].append({"role": "assistant", "content": f"⚠️ The AI service failed: {type(e).__name__}: {str(e)[:300]}.{hint}"})
        st.rerun()
    if chat["messages"] and st.button("Clear conversation"):
        st.session_state.pop("chat")
        st.rerun()

# ---------------------------------------------------------------------------
with tab_data:
    st.subheader("Source data and change log")
    st.caption("Edit any source table directly (as a reviewer would to test the app). Rules still apply on read: "
               "duplicate IDs are de-duplicated, history tables use the latest version ≤ the snapshot date.")
    tname = st.selectbox("Table", store.SOURCE_TABLES, index=store.SOURCE_TABLES.index("opp_history"))
    raw = store.load_raw_table(E, tname)
    st.caption(f"{len(raw)} rows (raw, including import-retry duplicates).")
    edited_raw = st.data_editor(raw, num_rows="dynamic", width="stretch", key=f"raw_{tname}", height=380)
    id_col = sd.ID_COLUMNS.get(tname)
    if st.button(f"Save {tname}"):
        if id_col and edited_raw[id_col].isna().any():
            st.error(f"Every row needs a {id_col}.")
        else:
            store.replace_source_table(E, tname, edited_raw)
            st.success("Saved. All analytics now use the edited data.")
            st.rerun()
    c1, c2 = st.columns(2)
    c1.download_button("Download this table (CSV)", raw.to_csv(index=False), f"{tname}.csv", "text/csv")
    with open(store.SOURCE_XLSX, "rb") as fh:
        c2.download_button("Download original workbook", fh.read(), "Sponsor_Dataset.xlsx")
    st.markdown("**Change log**")
    st.dataframe(store.load_app_table(E, "change_log").sort_values("log_id", ascending=False).head(50),
                 hide_index=True, width="stretch")
