# Sponsor Growth Center: RISA Growth APM assignment (Track B: Sponsorship)

**Author:** Jay · IIT Madras
**Deliverables:** 3-slide strategy (PDF) · this working app (dashboard + campaign/task management + embedded AI copilot) · this README

The strategy targets **sponsorship cash collected before Shaastra** (IIT Madras, Chennai). The app is the command centre that would run that plan. It is built and tested on the provided **CampusFest 2025 Sponsor dataset**.

---

## 1. Research, assumptions and calculations (Slide 1)

### Evidence from the provided dataset (computed by `sponsor_data.py`)

| Metric (as of 20 Apr 2025) | Value |
|---|---|
| Brands researched / contacted | 180 / 180 |
| Brands replied / replied positively / meeting held / qualified | 109 / 74 / 60 / 60 |
| Opportunities / reached proposal / reached negotiation / confirmed | 58 / 46 / 39 / **24** |
| Contacted → confirmed | 13.3% |
| Confirmed reported value | ₹22.4L (₹20.0L cash-type, ₹2.4L in-kind), average ₹93.3K |
| Targets (revised plan) | 55 qualified (actual 60), 28 partnerships (actual 24) |
| Warm channels (intros, interest form, creator referrals) | 44 brands → 24 confirmed (~55%), 24 won / 1 lost |
| Cold channels (email, LinkedIn, revival) | 33 opportunities → 0 won; all 7 opt-outs; all 26 still-open deals |
| Speed | Median 10 days from creation to confirmation; won deals never sat > 5 days in a stage; 0 of 26 deals idle ≥ 7 days ever closed |

### Shaastra inputs

| Input | Value | Source |
|---|---|---|
| Raised last edition | ₹1.7 Cr | Organiser estimate |
| Title sponsor | ₹18–20L | Organiser estimate |
| Brands reached | 500+ | Organiser estimate |
| Outreach structure | Stage 1 (Jun–Jul): new brands. Stage 2 (Aug on): previous sponsors. Most sponsors return. | Organiser estimate |
| Scale | Shaastra 2026: 27th edition, ~80 events, 130 stalls, ~80,000 visitors expected, 750+ student organisers | IIT Madras press release (26 Dec 2025); ETV Bharat; Careers360 |
| Sponsors last edition | ~70 (average ₹2.43L) | **Assumption**, to validate |
| Pre-fest collection rate | 92% base, 95% stretch (50% advance at signing) | **Assumption** |

### Funnel model (all ₹ in lakh; script: `strategy/funnel_model.py`; benchmarks: `strategy/slide1_benchmarks.md`)

| Segment | Base | Stretch |
|---|---|---|
| Returning: 70 → conversations → proposals → renew | 95% × 92% × 91.5% = 80% → 56 × ₹2.62L (+8% price) = **146.8** | 98% × 95% × 94.5% = 88% → 61.6 × ₹2.91L (+20% upsell) = **179.5** |
| Warm new: leads × conversion × average deal | 50 × 45% = 22.5 × 1.5 = **33.8** | 90 × 50% = 45 × 1.75 = **78.8** |
| Cold new: brands × qualify × sign × average deal | 450 × 16% = 72 × 12% = 8.6 × 1.2 = **10.4** | 600 × 18% = 108 × 20% = 21.6 × 1.4 = **30.2** |
| **Signed** | **190.9 (+12%)**, ~87 deals | **288.5 (+70%)**, ~128 deals |
| **Cash collected pre-fest** | × 92% = **175.7** | × 95% = **274.0** |

How the inputs were chosen:
- **Warm conversion:** 45–50% sits below the dataset's ~55% to allow for synthetic optimism.
- **Cold qualify rate:** 16% is the dataset rate (24 of 148 cold brand touches).
- **Cold sign rate:** 12–20% is an assumption. It holds only if the qualify-first gate is enforced. In the dataset, cold deals opened without qualification won 0.

## 2. Prioritisation framework (Slide 2)

Bets are ranked by **ICE = Impact × Confidence × Ease** (each 1–10). Confidence is scored from dataset evidence. Contributions map one-to-one to the funnel segments, so they sum to the target.

| # | Bet | Base / stretch | ICE |
|---|---|---|---|
| 1 | Renewal Accelerator (ROI report, early lock-in, upsell) | ₹1.47 / 1.80 Cr (+₹19L / +₹52L vs 75% renewal at flat prices) | 576 |
| 2 | Warm Intro Engine (intro ask at renewal, alumni drive) | ₹26L / ₹61L | 504 |
| 3 | Qualify-first + 7-day rule | ₹6L / ₹18L, and frees team capacity | 432 |
| 4 | Inbound Sponsor Magnet | ₹8L / ₹18L | 252 |
| 5 | Startup Pavilion packs | ₹4L / ₹12L | 150 |

**Rejected:**
- Mass cold email: 0 wins and all opt-outs in the data.
- Paid lead lists and commission agencies.
- A celebrity show to lure sponsors.

**Paused:** dormant-revival at scale (0 wins from 20 brands).

## 3. The app

| Tab | What it does |
|---|---|
| **Overview** | KPIs vs targets, funnel, net confirmed partnerships over time against goal versions, weekly activity, forecast, and cash-collected status. |
| **Campaigns & decisions** | Per-campaign Scale / Change / Stop / Hold verdict with the reasons and thresholds behind it (same rules as Slide 3). Charts, campaign plans (status, budget, spend, targets), and adding a new campaign. |
| **Pipeline** | Filterable deal list with days in stage and stale flags. One-click follow-up tasks for stale deals. Forms to move a deal's stage, create opportunities, update qualification and record cash receipts. |
| **Tasks** | Editable task board (owner, due date, status, priority, linked campaign or deal). Shows overdue and copilot-created counts. |
| **AI copilot** | Gemini with function calling over live data (see below). |
| **Data** | Edit any raw source table, download the data, view the change log, and reset to the original data from the sidebar. |

A **snapshot date** in the sidebar drives everything. Each view shows the state at the end of that day (IST), with no later outcomes leaking in.

### Data rules implemented (from the dataset's Read me)

- Import-retry duplicates are dropped by stable ID (6 interaction rows, 2 qualification rows, 4 opportunity-history rows).
- Full-state histories use the **latest version ≤ cutoff** per entity. They are never summed. A confirmed-then-withdrawn deal (Cobalt Learning) is handled correctly.
- Brand-level and opportunity-level populations are kept separate. A reply ≠ qualification ≠ confirmed partnership.
- Reported value is **not** cash. Cash collected stays "unknown" until receipts are recorded in the app.
- Edits to deals and qualification are **appended as new history versions** and logged.

### AI copilot design

- **Grounded:** it has 13 read tools, which run the same code as the dashboard against the current database and snapshot date:
  - overview, funnel, campaign performance, pipeline, stale deals, stage conversion
  - owner/industry breakdown, weekly trend, compare two dates
  - brand history, tasks, data coverage, calculate
- **Reliable calculations:** a `calculate` tool evaluates arithmetic exactly with a safe AST evaluator, so the model doesn't do mental math.
- **Diagnosis and recommendations:** it uses the same Scale/Change/Stop rules as the dashboard, and is told to label what is evidence and what is judgement.
- **Execution with confirmation:** `propose_task` and `propose_campaign_status` create proposals. They show up as Confirm/Discard cards, and nothing is saved until the user confirms.
- **Resilience:** busy-model errors (503/429/timeouts) are retried with backoff, then the copilot falls back to backup models (`GEMINI_FALLBACK_MODELS`). Each request has a 90-second timeout, and live step-by-step progress is shown.
- **Uncertainty:** `get_data_coverage` lists what the data cannot answer:
  - cash received
  - spend and ROI
  - causal impact
  - real companies

  The system prompt requires the copilot to say so, flag small samples and never invent figures.
- **Follow-ups:** the conversation history, including tool calls, is kept for the session. A "Data used" expander shows every tool call behind each answer.

## 4. Setup

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add GEMINI_API_KEY
streamlit run app.py
```

Without `DATABASE_URL`, the app uses a local SQLite file, seeded automatically from `data/Sponsor_Dataset.xlsx` on first run.

**Persistent deployment: Supabase + Streamlit Community Cloud**

1. In Supabase, click **Connect** at the top of the project. Copy the **Session pooler** URI and put your database password into it.
2. Push this folder to a GitHub repo. Don't commit `.streamlit/secrets.toml`; it is git-ignored.
3. On share.streamlit.io: **Create app**, pick the repo, set the main file to `app.py`, and set Python to 3.12.
4. Under **Advanced settings → Secrets**, paste:
   ```toml
   GEMINI_API_KEY = "..."
   GEMINI_MODEL = "gemini-3.8-flash"
   DATABASE_URL = "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
   ```
5. Deploy. On first load, the app creates the tables in Supabase and seeds them with the original data.

## 5. Tools used

- **Languages and libraries:** Python 3.12, pandas, Streamlit, Plotly, SQLAlchemy.
- **Database and AI:** Supabase Postgres (free tier) and Google Gemini 3.8 Flash via the `google-genai` SDK (free tier from Google AI Studio).
- **Build assistance:** the app was built with help from an AI coding assistant (Claude). All metrics were **independently re-computed** from the raw sheets and matched. Examples: 17 confirmed / ₹15.05L / 55 qualified on 15 Mar; 24 / ₹22.4L / 60 at the end.
- **Reuse:** no templates were reused.

## 6. Testing done

- **Headless UI run:** a Streamlit AppTest run of every tab, plus a change of snapshot date. No exceptions.
- **Copilot tools:** all 15 tools were run on live data. The function-calling loop was tested with a scripted model, covering multi-tool turns, tool results going back to the model, and proposals awaiting confirmation.
- **Changed-data test:** a raw history row was edited and a new "lost" version added. Partnerships went from 24 → 23 and value from ₹22.4L → ₹23.2L, and the dashboard and copilot updated together. A snapshot taken before the edit date was unaffected.
- **Forecast backtest:** on the same data, projections were 20.2 (1 Mar), 27.7 (15 Mar) and 25.5 (5 Apr), against an actual final of 24.

## 7. Known limitations

- **Small, synthetic data:** 24 wins, so rates are indicative. Campaign attribution is observational.
- **No spend or cash data in the source:** cost per deal and cash collected appear only once entered in the app.
- **Live copilot not tested in the build environment:** the build environment couldn't reach the Gemini API, so the live model behaviour was verified only after deployment. The tools and loop were tested offline.
- **Thresholds:** the Scale/Change/Stop thresholds are heuristics taken from this dataset, and they should be re-tuned on real Shaastra data.
- **No user accounts:** anyone with the link can edit. This is fine for a demo; a production version needs authentication.
