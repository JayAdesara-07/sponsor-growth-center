# CampusFest 2025 sponsor data: benchmarks for Slide 1

Source: the provided Sponsor dataset (synthetic), cleaned with `sponsor_data.py`. Cleaning steps: import retries deduplicated by ID, the latest history version per entity, and the end-of-day IST cutoff. Figures are as of 20 Apr 2025 unless a date is given. Key numbers were recomputed independently from the raw sheets and match.

## Overall funnel

| Stage | Count | From previous | From contacted |
|---|---|---|---|
| Brands researched | 180 | | |
| Brands contacted | 180 | 100% | 100% |
| Brands replied | 109 | 60.6% | 60.6% |
| Brands replied positively | 74 | 67.9% | 41.1% |
| Brands with meeting held | 60 | 81.1% | 33.3% |
| Brands qualified | 60 | 100% | 33.3% |
| Opportunities created | 58 | n/a (brand → deal) | 32.2% |
| Reached proposal | 46 | 79.3% | 25.6% |
| Reached negotiation | 39 | 84.8% | 21.7% |
| **Partnerships confirmed** | **24** | 61.5% | **13.3%** |

- **Targets (revised plan, 15 Mar):** 60 of 55 qualified brands (109%). 24 of 28 confirmed partnerships (86%), so **4 short**.
- **Value:** ₹22.4L reported. Of that, ₹20.0L is cash-type and ₹2.4L in-kind. The average deal is ₹93.3K.
- **Cash actually collected: not in the data.** Reported value is not proof of bank receipt.
- **Lost or withdrawn:** 8. **Still open at the end:** 26 deals worth ₹14.4L in proposed value. The festival has already happened, so these will never close.

## Key insight: warm channels made every rupee

| Channel group | Campaigns | Brands contacted | Opportunities | Confirmed | Value | Contacted → confirmed |
|---|---|---|---|---|---|---|
| **Warm / inbound** | Warm Intros, Interest Form, Creator Referrals | 44 | 25 | **24** | **₹22.4L** | **~55%** |
| **Cold** | Discovery Email, LinkedIn, Past Revival | 148* | 33 | **0** | ₹0 | 0% |

\*These are brand touches per campaign. 12 brands were touched by two campaigns.

- In the warm channels, 24 deals were won and 1 lost (96% win rate on deals with an outcome).
- In the cold channels, 0 deals were won and 7 were lost or withdrawn. All 26 open deals are stuck here.
- Cold email used the most effort (224 outreach attempts, a 37% brand reply rate) and caused all 7 opt-outs.
- **A process leak:** 15 cold opportunities were opened on brands that were *never qualified* (still dormant, engaged or unqualified). None of them progressed.

Per campaign:

| Campaign | Contacted | Reply % | Meeting % | Confirmed | Value | Avg deal |
|---|---|---|---|---|---|---|
| Warm Partner Introductions | 8 | 100 | 100 | 8 | ₹7.85L | ₹98K |
| Creator Network Referrals | 19 | 100 | 79 | 9 | ₹7.85L | ₹87K |
| Partner Interest Form | 17 | 100 | 76 | 7 | ₹6.70L | ₹96K |
| Brand Leader LinkedIn | 37 | 81 | 27 | 0 | n/a | n/a |
| Past Conversation Revival | 20 | 50 | 35 | 0 | n/a | n/a |
| Brand Discovery Email | 91 | 37 | 8 | 0 | n/a | n/a |

## Speed (gives you thresholds for Slide 3)

- **Opportunity created → confirmed:** median 10 days (range 5–13). **Proposal → confirmed:** median 5 days.
- **First touch → first meeting:** median 3 days.
- **No won deal ever sat in one stage for more than 5 days. All 26 deals that sat idle for 7+ days never closed.** This is a strong early warning sign. Suggested rule: if a deal is idle for 7 days, escalate it; if it's idle for 14, drop it.
- Weekly confirmations peaked from mid-February to early March (4 a week). New warm leads dried up after mid-March, and confirmations stopped after 31 March.

## By industry (small samples, so treat as directional)

| Industry | Brands | Qualify % | Confirmed | Avg deal |
|---|---|---|---|---|
| Consumer products | 36 | 47% | 5 | ₹90K |
| Education | 35 | 40% | 3 | ₹88K |
| Media | 35 | 31% | 4 | ₹71K |
| Mobility | 36 | 25% | 5 | ₹98K |
| Food & beverage | 37 | 22% | 6 | ₹92K |

## What this means for the strategy

1. **The bottleneck is the supply of warm leads, not closing.** Warm leads convert at about 55% from first contact. Only 44 such brands entered the funnel. The biggest growth lever is producing more warm leads: alumni and past-sponsor intros, a creator network, and an inbound form backed by marketing.
2. **Cold outreach should feed qualification, not the deal pipeline.** Add a rule that no deal is opened until the brand is qualified. That frees team time currently spent on 26 deals that will never close.
3. **Speed rules:** a 7-day idle alert and a 14-day kill rule, plus aiming for about 10 days from opening a deal to signing.
4. **Start earlier.** The warm pipeline ran out about 4 weeks before the fest.

## Forecast check (for Slide 3 and the dashboard)

The weighted forecast in `sponsor_data.weighted_forecast` works like this. Each open deal's win probability is its campaign's win rate, smoothed toward the overall win rate for its current stage. Stalled deals are cut to 10% of that probability. Nothing closes after the event starts.

Backtested on the same data:

| Snapshot date | Confirmed so far | Projected | Actual final |
|---|---|---|---|
| 1 Mar | 10 | 20.2 | 24 |
| 15 Mar | 17 | 27.7 | 24 |
| 5 Apr | 24 | 25.5 | 24 |

## Limitations to state honestly

- The data is synthetic, and there are only 24 won deals, so the rates are indicative.
- Campaign attribution only records where a brand came from. It doesn't prove the campaign caused the deal.
- **There is no spend or cost data,** so cost per deal and ROI by channel can't be computed. Effort can only be compared by number of attempts.
- **There is no cash-received data.** "Cash collected" can't be answered from this dataset.
