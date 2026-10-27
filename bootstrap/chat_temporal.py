"""Temporal links across exact, independently verifiable chat claims.

Pure projection: original messages are never rewritten. A later statement may
supersede an earlier expression, but no statement becomes a verified fact.
This uses local deterministic rules, with no provider/network requests.
"""
from collections import defaultdict

MAX_GROUPS=100
MAX_LINKS=200

def timeline(claims):
    """Input: vetted source-linked candidates ordered by increasing message ID."""
    groups=defaultdict(list)
    for row in claims:
        if row.get("kind") not in ("preference","plan","uncertainty"):
            continue
        if row.get("status")!="unverified":
            continue
        key=(row["kind"],row["key"])
        groups[key].append(row)
    links=[]
    topics=[]
    for (kind,key),rows in list(groups.items())[:MAX_GROUPS]:
        # Order is actual journal sequence, not an untrusted self-reported date.
        rows=sorted(rows,key=lambda r:(r["turn_id"],r["start"],r["end"]))
        last=rows[-1]
        transitions=0
        for before,after in zip(rows,rows[1:]):
            change=before["polarity"]!=after["polarity"]
            if change:
                transitions+=1
            if len(links)<MAX_LINKS:
                links.append({"from_turn":before["turn_id"],"to_turn":after["turn_id"],
                              "kind":kind,"relation":"changed" if change else "repeated"})
        topics.append({"kind":kind,"fingerprint":key,
                       "first_turn":rows[0]["turn_id"],"latest_turn":last["turn_id"],
                       "mentions":len(rows),"changes":transitions,
                       "latest_polarity":last["polarity"],
                       "certainty":"unverified_user_statement"})
    return {"topics":topics,"links":links,
            "verified_facts":0,"external_model_calls":0,
            "automatic_personality_changes":0}
