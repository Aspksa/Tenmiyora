"""Живая активность Мозга: импульсы вопросов, синапсы между темами, свежесть веток.

Только локальная SQLite. Импульс — это ветки, из которых пришли найденные
знания для одного вопроса (чат или поиск). Синапс — связь двух видимых веток:
общие источники и совместное использование в ответах.
"""
import json

from brain_growth import EFFECTIVE
from topic_aliases import projection

KEEP_PULSES = 60
MAX_SYNAPSES = 30


def init_schema(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS brain_usage(
          branch_id INTEGER PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 0, last_used TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brain_synapses(
          a INTEGER NOT NULL, b INTEGER NOT NULL, weight INTEGER NOT NULL DEFAULT 0,
          last_used TEXT NOT NULL, PRIMARY KEY(a,b));
        CREATE TABLE IF NOT EXISTS brain_pulses(
          id INTEGER PRIMARY KEY, time TEXT NOT NULL, origin TEXT NOT NULL, branches TEXT NOT NULL);
    """)


def record(db, branch_ids, origin, clock):
    """Отметить, что знания этих веток только что понадобились."""
    mapping = projection(db)
    visible = sorted({mapping.get(b, b) for b in branch_ids if b is not None})
    if not visible:
        return None
    for branch in visible:
        db.execute("""INSERT INTO brain_usage(branch_id,uses,last_used) VALUES(?,1,?)
            ON CONFLICT(branch_id) DO UPDATE SET uses=uses+1,last_used=excluded.last_used""", (branch, clock))
    for i, a in enumerate(visible):
        for b in visible[i + 1:]:
            db.execute("""INSERT INTO brain_synapses(a,b,weight,last_used) VALUES(?,?,1,?)
                ON CONFLICT(a,b) DO UPDATE SET weight=weight+1,last_used=excluded.last_used""", (a, b, clock))
    pulse = db.execute("INSERT INTO brain_pulses(time,origin,branches) VALUES(?,?,?)",
                       (clock, origin, json.dumps(visible))).lastrowid
    db.execute("DELETE FROM brain_pulses WHERE id<=?", (pulse - KEEP_PULSES,))
    return pulse


def pulses(db, since=0):
    rows = db.execute("SELECT id,time,origin,branches FROM brain_pulses WHERE id>? ORDER BY id LIMIT 20",
                      (int(since),)).fetchall()
    last = db.execute("SELECT COALESCE(MAX(id),0) FROM brain_pulses").fetchone()[0]
    return {"pulses": [{"id": r["id"], "time": r["time"], "origin": r["origin"],
                        "branches": json.loads(r["branches"])} for r in rows], "last": last}


def _parents(db, mapping):
    return {r["id"]: mapping.get(r["parent"], r["parent"]) for r in db.execute("SELECT id,parent FROM branches")}


def activity(db):
    """Синапсы и время последней жизни веток для карты."""
    mapping = projection(db)
    parents = _parents(db, mapping)
    links = {}

    def add(a, b, shared=0, used=0):
        a, b = mapping.get(a, a), mapping.get(b, b)
        # Ветка и её родитель уже соединены деревом, а одна ветка — сама с собой.
        if a == b or parents.get(a) == b or parents.get(b) == a:
            return
        key = (min(a, b), max(a, b))
        item = links.setdefault(key, {"a": key[0], "b": key[1], "shared": 0, "used": 0})
        item["shared"] += shared
        item["used"] += used

    sources = {}
    for row in db.execute(f"SELECT DISTINCT branch,source_type,source_id FROM ({EFFECTIVE})"):
        sources.setdefault((row["source_type"], row["source_id"]), set()).add(mapping.get(row["branch"], row["branch"]))
    for branches in sources.values():
        ordered = sorted(branches)
        if len(ordered) > 8:  # Огромный документ обо всём не связывает всё со всем.
            continue
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                add(a, b, shared=1)
    for row in db.execute("SELECT a,b,weight FROM brain_synapses"):
        add(row["a"], row["b"], used=row["weight"])
    ranked = sorted(links.values(), key=lambda x: -(x["shared"] + 2 * x["used"]))[:MAX_SYNAPSES]
    for item in ranked:
        item["weight"] = item["shared"] + 2 * item["used"]

    alive = {}
    for row in db.execute(f"SELECT branch,MAX(created) AS t FROM ({EFFECTIVE}) GROUP BY branch"):
        target = mapping.get(row["branch"], row["branch"])
        alive[target] = max(alive.get(target, ""), row["t"] or "")
    for row in db.execute("SELECT branch_id,last_used FROM brain_usage"):
        target = mapping.get(row["branch_id"], row["branch_id"])
        alive[target] = max(alive.get(target, ""), row["last_used"])
    last = db.execute("SELECT COALESCE(MAX(id),0) FROM brain_pulses").fetchone()[0]
    return {"synapses": ranked, "alive": {str(k): v for k, v in alive.items()}, "last_pulse": last}
