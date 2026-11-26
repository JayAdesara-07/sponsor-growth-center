"""Slide 1 funnel model: Shaastra sponsorship, next full cycle. All money in INR lakh."""
LAST_YEAR_L = 170          # Het: total raised last edition
N_PREV = 70                # ASSUMPTION: sponsors last edition (to confirm)
AVG_PREV = LAST_YEAR_L / N_PREV

S = {
 "base": dict(
   ret=dict(conv=0.95, prop=0.92, sign=0.915, uplift=0.08),
   warm=dict(leads=50, rate=0.45, deal=1.5),
   cold=dict(brands=450, qual=0.16, sign=0.12, deal=1.2),
   collect=0.92),
 "stretch": dict(
   ret=dict(conv=0.98, prop=0.95, sign=0.945, uplift=0.20),
   warm=dict(leads=90, rate=0.50, deal=1.75),
   cold=dict(brands=600, qual=0.18, sign=0.20, deal=1.4),
   collect=0.95),
}
for name, a in S.items():
    r=a["ret"]; conv=N_PREV*r["conv"]; prop=conv*r["prop"]; sig=prop*r["sign"]
    ret_v = sig*AVG_PREV*(1+r["uplift"])
    w=a["warm"]; w_n=w["leads"]*w["rate"]; w_v=w_n*w["deal"]
    c=a["cold"]; c_q=c["brands"]*c["qual"]; c_n=c_q*c["sign"]; c_v=c_n*c["deal"]
    signed=ret_v+w_v+c_v; cash=signed*a["collect"]
    print(f"== {name}")
    print(f" returning: {N_PREV} -> conv {conv:.1f} -> prop {prop:.1f} -> signed {sig:.1f} ({sig/N_PREV:.0%}) x Rs{AVG_PREV*(1+r['uplift']):.2f}L = {ret_v:.1f}L")
    print(f" warm new : {w['leads']} leads x {w['rate']:.0%} = {w_n:.1f} deals x Rs{w['deal']}L = {w_v:.1f}L")
    print(f" cold new : {c['brands']} -> qualified {c_q:.0f} -> signed {c_n:.1f} x Rs{c['deal']}L = {c_v:.1f}L")
    print(f" SIGNED {signed:.1f}L ({signed/LAST_YEAR_L-1:+.0%} vs last yr) | deals {sig+w_n+c_n:.0f} | CASH pre-fest @{a['collect']:.0%} = {cash:.1f}L")
    print(f" conversations to run: {conv+w['leads']+c_q:.0f}")
