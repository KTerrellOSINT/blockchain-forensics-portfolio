"""
Bitcoin Wallet Red-Flag Scorer (v3 - Value-Weighted + Statistical Model)
Kathryn Terrell | OSINT / Blockchain Analysis Work Sample | June 29, 2026

v3 changes from v2, based on a code review and a full day of testing against
real cases (DarkSide/Colonial Pipeline laundering chain, a confirmed "double
your Bitcoin" advance-fee scam, a 2-year fake-investment sweep wallet, and a
~3-year, 2,000-transaction wallet later identified as a likely OTC/trading
operation via repeated multi-exchange contact):

  1. Sweep dominance is now measured by BTC VALUE, not just transaction
     count. A wallet with 99 dust payouts and 1 large payout no longer
     looks identical to a wallet with 99 large payouts and 1 dust payout.
  2. Amount clustering now uses the coefficient of variation (stdev/mean)
     instead of a fixed "% within 2% of average" cutoff -- a more
     statistically standard way to measure how tightly a distribution
     clusters, regardless of the wallet's absolute scale.
  3. The "consolidation+fan-out" indicator (many sources AND many
     destinations) is downweighted on its own, since this same shape
     also describes exchanges, payment processors, and OTC desks --
     exactly the false-positive risk discovered in today's testing. It
     now only carries meaningful weight when paired with a second,
     stronger indicator (clustering, sweep dominance, or mixing contact).
  4. A short investigator-style statistics block is printed alongside
     the indicator checks (mean/median deposit, lifetime, largest payout,
     etc.), independent of the score, so a human reviewer always has the
     underlying numbers, not just a verdict.

Architecture is intentionally kept as a single, readable script (not split
into classes/modules) since the goal here is a transparent, walkable
portfolio artifact rather than a production system -- every number the
score is built from is visible in the printed output.

HOW TO USE:
  1. Go to walletexplorer.com and look up any Bitcoin wallet
  2. Click "CSV Export" on the wallet page to download the transaction file
  3. Update the path variable below to point to your downloaded CSV file
  4. Run the script in Python 3.x -- no external libraries required
"""

import csv
import os
import statistics
from datetime import datetime

# ---------------------------------------------------------------------------
# INPUT FILE -- update this path to point to your WalletExplorer CSV file
# Download from walletexplorer.com by clicking "CSV Export" on any wallet page
# ---------------------------------------------------------------------------

# Windows users -- example:
path = r"C:\path\to\your\walletexplorer-export.csv"

# Mac/Linux users -- uncomment and use this format instead:
# path = os.path.expanduser("~/Downloads/your-walletexplorer-file.csv")

# ---------------------------------------------------------------------------
# CONFIGURATION -- tune behavior here without touching the logic below
# ---------------------------------------------------------------------------
CONFIG = {
    "DRAIN_TO_ZERO_PCT": 1,         # remaining balance, as % of total received
    "CLUSTER_CV_THRESHOLD": 0.15,   # coefficient of variation below this = tight clustering
    "SWEEP_VALUE_CRITICAL": 95,     # % of payout VALUE to one destination = hard floor
    "SWEEP_VALUE_WARNING": 70,
    "DORMANCY_LONG_DAYS": 30,
    "DORMANCY_FAST_SECONDS": 3600,
    "ORGANIC_STRONG_PCT": 25,       # % of counterparties seen 2+ times
    "ORGANIC_MODERATE_PCT": 15,
    "MIN_SAMPLE_FOR_STATS": 5,      # minimum deposits before clustering/CV is meaningful
}

# ---------------------------------------------------------------------------
# LOAD AND PARSE
# ---------------------------------------------------------------------------
with open(path) as file:
    reader = csv.reader(file)
    rows = list(reader)

data_rows = rows[2:]

events = []
for row in data_rows:
    date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    if row[2] != "":
        events.append({"date": date, "type": "deposit", "amount": float(row[2]), "who": row[1]})
    if row[3] != "" and row[4] != "(fee)":
        events.append({"date": date, "type": "payout", "amount": float(row[3]), "who": row[4]})

events.sort(key=lambda e: e["date"])

deposits = [e for e in events if e["type"] == "deposit"]
payouts = [e for e in events if e["type"] == "payout"]

print("Loaded", len(deposits), "deposits and", len(payouts), "payouts")

# ---------------------------------------------------------------------------
# INVESTIGATOR SUMMARY STATISTICS (informational -- not scored)
# ---------------------------------------------------------------------------
print("\n--- SUMMARY STATISTICS ---")
if deposits:
    dep_amounts = [d["amount"] for d in deposits]
    print("Deposits: total", round(sum(dep_amounts), 8), "BTC | mean", round(statistics.mean(dep_amounts), 8),
          "| median", round(statistics.median(dep_amounts), 8))
if payouts:
    pay_amounts = [p["amount"] for p in payouts]
    print("Payouts:  total", round(sum(pay_amounts), 8), "BTC | mean", round(statistics.mean(pay_amounts), 8),
          "| median", round(statistics.median(pay_amounts), 8), "| largest", round(max(pay_amounts), 8))
if deposits and payouts:
    lifetime = max(e["date"] for e in events) - min(e["date"] for e in events)
    print("Wallet lifetime (first event to last):", lifetime)

print("\n--- INDICATOR CHECKS ---")

score = 0
notes = []

# ---------------------------------------------------------------------------
# INDICATOR 1: Drains to (near) zero  [weight: 1]
# ---------------------------------------------------------------------------
total_received = sum(d["amount"] for d in deposits)
total_sent = sum(p["amount"] for p in payouts)
remaining = round(total_received - total_sent, 8)
remaining_pct = (remaining / total_received * 100) if total_received > 0 else 0

drains_to_zero = remaining_pct <= CONFIG["DRAIN_TO_ZERO_PCT"]
if drains_to_zero:
    score += 1
    notes.append("Drains to (near) zero balance")
    print("[+1] Drains to zero. Received:", round(total_received, 8), "| Sent:", round(total_sent, 8))
else:
    print("[ 0] No drain-to-zero signal. Remaining:", remaining, "(", round(remaining_pct, 1), "% )")

# ---------------------------------------------------------------------------
# INDICATOR 2: Consolidation / fan-out shape
# [weight: 1 alone -- this shape also describes exchanges, payment
#  processors, and OTC desks, so it only becomes meaningful weight 2
#  when paired with a stronger indicator below (clustering or sweep).]
# ---------------------------------------------------------------------------
shape_triggered = False
if len(deposits) >= 5 and len(payouts) <= 3:
    shape_triggered = True
    score += 1
    notes.append("Consolidation pattern: many sources, few payouts")
    print("[+1] Consolidation -", len(deposits), "deposits ->", len(payouts), "payout(s)")
elif len(deposits) <= 3 and len(payouts) >= 5:
    shape_triggered = True
    score += 1
    notes.append("Fan-out pattern: few sources, many payouts")
    print("[+1] Fan-out -", len(deposits), "deposit(s) ->", len(payouts), "payouts")
elif len(deposits) >= 5 and len(payouts) >= 5:
    shape_triggered = True
    score += 1
    notes.append("Both consolidation and fan-out present (weak signal alone)")
    print("[+1] Consolidation+fan-out -", len(deposits), "deposits,", len(payouts),
          "payouts (NOTE: also typical of exchanges/payment processors -- weak alone)")
else:
    print("[ 0] No major consolidation/fan-out shape. Deposits:", len(deposits), "| Payouts:", len(payouts))

# ---------------------------------------------------------------------------
# INDICATOR 3: Tight amount clustering, via coefficient of variation
# [weight: 2] Low CV = amounts tightly clustered (many victims targeting
# the same advertised value); high CV = ordinary, irregular activity.
# ---------------------------------------------------------------------------
cluster_cv = None
clustering_triggered = False
if len(deposits) >= CONFIG["MIN_SAMPLE_FOR_STATS"]:
    dep_amounts = [d["amount"] for d in deposits]
    mean_dep = statistics.mean(dep_amounts)
    stdev_dep = statistics.stdev(dep_amounts)
    cluster_cv = round(stdev_dep / mean_dep, 4) if mean_dep > 0 else None
    if cluster_cv is not None and cluster_cv <= CONFIG["CLUSTER_CV_THRESHOLD"]:
        clustering_triggered = True
        score += 2
        notes.append("Tight amount clustering (coefficient of variation = " + str(cluster_cv) + ")")
        print("[+2] Amount clustering -- CV =", cluster_cv, "(mean", round(mean_dep, 8), "BTC) -- tightly clustered")
    else:
        print("[ 0] No clustering. CV =", cluster_cv, "(higher = more spread out)")
else:
    print("[ 0] Not enough deposits to compute clustering statistics")

# ---------------------------------------------------------------------------
# INDICATOR 4: Sweep dominance, weighted by BTC VALUE (not transaction count)
# [weight: 2 if >=70% of value, weight: 3 if >=95% -- treated as a hard
#  floor at the critical level, since this is strong evidence regardless
#  of wallet size.]
# ---------------------------------------------------------------------------
value_dominance_pct = 0
sweep_hard_floor = False
if len(payouts) >= 2:
    dest_value = {}
    for p in payouts:
        dest_value[p["who"]] = dest_value.get(p["who"], 0) + p["amount"]
    top_dest, top_value = sorted(dest_value.items(), key=lambda x: x[1], reverse=True)[0]
    total_payout_value = sum(dest_value.values())
    value_dominance_pct = round(top_value / total_payout_value * 100, 1) if total_payout_value > 0 else 0

    if value_dominance_pct >= CONFIG["SWEEP_VALUE_CRITICAL"]:
        sweep_hard_floor = True
        score += 3
        notes.append("Near-total sweep dominance by VALUE (" + top_dest[:10] + ", " + str(value_dominance_pct) + "% of BTC sent)")
        print("[+3] Near-total sweep dominance (by value) -", top_dest[:10], "received", round(top_value, 8),
              "of", round(total_payout_value, 8), "BTC sent (", value_dominance_pct, "% )")
    elif value_dominance_pct >= CONFIG["SWEEP_VALUE_WARNING"]:
        score += 2
        notes.append("Sweep-like dominance by VALUE (" + top_dest[:10] + ", " + str(value_dominance_pct) + "%)")
        print("[+2] Sweep-like dominance (by value) -", top_dest[:10], round(value_dominance_pct, 1), "% of BTC sent")
    else:
        print("[ 0] No value-based sweep dominance. Top destination only", value_dominance_pct, "% of BTC sent")
else:
    print("[ 0] Not enough payouts to check destination dominance")

# ---------------------------------------------------------------------------
# INDICATOR 5: Dormancy  [weight: 1]
# ---------------------------------------------------------------------------
if len(deposits) > 0 and len(payouts) > 0:
    payout_dates = sorted(p["date"] for p in payouts)

    longest_idle_gap = max(
        (payout_dates[i + 1] - payout_dates[i] for i in range(len(payout_dates) - 1)),
        default=(payout_dates[-1] - payout_dates[0])
    )

    turnaround_times = []
    for d in deposits:
        later_payouts = [p["date"] for p in payouts if p["date"] >= d["date"]]
        if later_payouts:
            turnaround_times.append(min(later_payouts) - d["date"])

    median_turnaround = statistics.median(turnaround_times) if turnaround_times else None

    print("\nLongest idle gap between payouts:", longest_idle_gap)
    if median_turnaround is not None:
        print("Median time from a deposit to the next payout:", median_turnaround)

    if longest_idle_gap.days >= CONFIG["DORMANCY_LONG_DAYS"]:
        score += 1
        notes.append("Long idle gap with no payout activity (" + str(longest_idle_gap.days) + " days)")
        print("[+1] Long idle gap -", longest_idle_gap.days, "days with no payouts")
    elif median_turnaround is not None and median_turnaround.total_seconds() < CONFIG["DORMANCY_FAST_SECONDS"]:
        score += 1
        notes.append("Very fast typical turnaround (under 1 hour, median)")
        print("[+1] Fast turnaround - median under 1 hour")
    else:
        print("[ 0] No dormancy signal.")

# ---------------------------------------------------------------------------
# INDICATOR 6: Repeat counterparties  [DAMPENER]
# ---------------------------------------------------------------------------
all_counterparties = [e["who"] for e in events]
counterparty_counts = {}
for who in all_counterparties:
    counterparty_counts[who] = counterparty_counts.get(who, 0) + 1

repeats = sum(1 for count in counterparty_counts.values() if count >= 2)
unique_counterparties = len(counterparty_counts)
repeat_pct = round(repeats / unique_counterparties * 100, 1) if unique_counterparties > 0 else 0

print("\nUnique counterparties:", unique_counterparties)
print("Counterparties seen 2+ times:", repeats, "(", repeat_pct, "% )")

organic_dampener = 0
if repeat_pct >= CONFIG["ORGANIC_STRONG_PCT"]:
    organic_dampener = 2
    print("[-2] Strong organic-usage signal (high counterparty reuse)")
elif repeat_pct >= CONFIG["ORGANIC_MODERATE_PCT"]:
    organic_dampener = 1
    print("[-1] Moderate organic-usage signal")
else:
    print("[ 0] No organic-usage dampener")

# ---------------------------------------------------------------------------
# INDICATOR 7: Known mixing-service contact  [weight: 3, hard floor]
# ---------------------------------------------------------------------------
mixing_hits = [row for row in data_rows if "coinjoin" in row[4].lower()]
mixing_present = len(mixing_hits) > 0

if mixing_present:
    total_to_mixer = sum(float(row[3]) for row in mixing_hits)
    score += 3
    notes.append("Funds sent to a known mixing service, " + str(len(mixing_hits)) + " transaction(s)")
    print("[+3] Mixing-service contact -", len(mixing_hits), "transaction(s), total", round(total_to_mixer, 8), "BTC")
else:
    print("[ 0] No known mixing-service contact detected")

# ---------------------------------------------------------------------------
# INDICATOR 8: Named/known service contact (informational, not scored)
# ---------------------------------------------------------------------------
named_services = []
for row in data_rows:
    received_from = row[1]
    sent_to = row[4]
    if received_from != "" and ("." in received_from or "coinjoin" in received_from.lower()):
        named_services.append(("received from", received_from, row[0]))
    if sent_to != "" and sent_to != "(fee)" and ("." in sent_to or "coinjoin" in sent_to.lower()):
        named_services.append(("sent to", sent_to, row[0]))

if len(named_services) > 0:
    unique_names = set(name for direction, name, date in named_services)
    notes.append("Contact with named/known service(s): " + ", ".join(unique_names))
    print("\n[INFO] Named service contact found (" + str(len(named_services)) + " total contact(s) across "
          + str(len(unique_names)) + " service(s)):")
    for direction, name, date in named_services[:10]:
        print("   ", date, "-", direction, "-", name)
    if len(named_services) > 10:
        print("    ... and", len(named_services) - 10, "more (see full notes list)")
else:
    print("\n[ 0] No named/known service contact detected")

# ---------------------------------------------------------------------------
# FINAL SCORE
# ---------------------------------------------------------------------------
raw_score = score
final_score = max(0, score - organic_dampener)

hard_floor_triggered = mixing_present or sweep_hard_floor
if hard_floor_triggered:
    final_score = max(final_score, raw_score)

print("\n=== SUMMARY ===")
print("Indicators triggered:")
for n in notes:
    print(" -", n)
print("\nRaw severity score:", raw_score)
print("Organic-usage dampener:", "(suppressed - hard floor active)" if hard_floor_triggered else ("-" + str(organic_dampener)))
print("Final severity score:", final_score)

if final_score >= 5:
    print("\nOverall risk: HIGH")
elif final_score >= 3:
    print("Overall risk: MODERATE")
elif final_score >= 1:
    print("Overall risk: LOW-MODERATE")
else:
    print("Overall risk: LOW")

if hard_floor_triggered:
    print("(Note: a high-severity finding -- near-total sweep dominance by VALUE and/or confirmed")
    print(" mixing-service contact -- was present. This cannot be downgraded by ordinary")
    print(" counterparty-reuse patterns, regardless of wallet transaction volume.)")

if len(notes) == 1 and "Both consolidation and fan-out present" in notes[0]:
    print("\n(Caution: the only indicator triggered is the generic consolidation/fan-out shape,")
    print(" which is also typical of exchanges, payment processors, and OTC desks. Treat this")
    print(" result as inconclusive without a stronger paired signal.)")
