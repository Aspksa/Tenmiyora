"""Read-only reconstruction of time-aware chat memory from the existing journal."""
import hashlib
from chat_semantic import validate_claim
from chat_temporal import timeline

def reconstruct(journal):
    with journal.lock,journal._db() as db:
        rows=db.execute(
            "SELECT c.turn_id,c.kind,c.start,c.end,c.fingerprint,c.polarity,c.status,"
            "t.text,t.digest,t.role FROM candidates c JOIN turns t ON t.id=c.turn_id "
            "ORDER BY c.turn_id,c.start,c.id").fetchall()
    clean=[]
    invalid=0
    for turn,kind,start,end,key,polarity,status,original,digest,role in rows:
        claim={"kind":kind,"start":start,"end":end,"key":key,
               "polarity":polarity,"status":status}
        valid=(role=="user" and hashlib.sha256(original.encode("utf-8")).hexdigest()==digest
               and validate_claim(original,claim))
        if valid:
            clean.append(dict(claim,turn_id=turn))
        else:
            invalid+=1
    result=timeline(clean)
    result["evidence_checked"]=len(rows)
    result["invalid_evidence"]=invalid
    return result
