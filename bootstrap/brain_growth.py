"""Рост Мозга для интерфейса: график по дням, дневник недели, уровни тем.

Только чтение SQLite. Знания считаются так же, как в дереве веток:
knowledge_items, а для веток без них — старые facts.
"""
from datetime import date, timedelta

from topic_aliases import projection

EFFECTIVE = """SELECT branch_id AS branch,source_type,source_id,created FROM knowledge_items
    UNION ALL
    SELECT f.branch,f.source_type,f.source_id,f.created FROM facts f WHERE NOT EXISTS
      (SELECT 1 FROM knowledge_items k WHERE k.branch_id=f.branch)"""

LEVELS = ((1, "Начальный"), (2, "Растущий"), (3, "Уверенный"), (4, "Глубокий"))


def level(count, sources):
    """Грубая шкала: объём знаний и число независимых источников."""
    if count < 5:
        return LEVELS[0]
    if count < 15 or sources < 2:
        return LEVELS[1]
    if count < 40 or sources < 3:
        return LEVELS[2]
    return LEVELS[3]


def _roots(db):
    """branch id -> (id корня, имя корня) с учётом объединённых синонимов."""
    rows = {r["id"]: r for r in db.execute("SELECT id,parent,name FROM branches")}
    mapping = projection(db)
    roots = {}
    for start in rows:
        node, seen = mapping.get(start, start), set()
        while node in rows and rows[node]["parent"] is not None and node not in seen:
            seen.add(node)
            node = mapping.get(rows[node]["parent"], rows[node]["parent"])
        if node in rows:
            roots[start] = (node, rows[node]["name"])
    return roots


def growth(db, days=30, offset_minutes=0):
    days = max(7, min(90, int(days)))
    offset = max(-840, min(840, int(offset_minutes)))
    shift = f"{offset:+d} minutes"
    today = date.fromisoformat(db.execute("SELECT date('now',?)", (shift,)).fetchone()[0])
    first = today - timedelta(days=days - 1)
    week = today - timedelta(days=6)

    per_day = {row["d"]: row["n"] for row in db.execute(
        f"SELECT date(created,?) AS d,COUNT(*) AS n FROM ({EFFECTIVE}) GROUP BY d", (shift,))}
    quality = {row["d"]: row["q"] for row in db.execute(
        """SELECT date(created,?) AS d,MAX(quality_score) AS q
           FROM brain_lab_generations GROUP BY d""", (shift,))}
    total = sum(n for d, n in per_day.items() if d and d < first.isoformat())
    series = []
    for index in range(days):
        day = (first + timedelta(days=index)).isoformat()
        added = per_day.get(day, 0)
        total += added
        series.append({"date": day, "added": added, "total": total,
                       "quality": quality.get(day)})

    roots = _roots(db)
    topics = {}
    for row in db.execute(f"SELECT branch,source_type,source_id,date(created,?) AS d FROM ({EFFECTIVE})", (shift,)):
        root = roots.get(row["branch"])
        if not root:
            continue
        item = topics.setdefault(root[0], {"id": root[0], "name": root[1], "count": 0,
                                           "sources": set(), "week": 0, "updated": ""})
        item["count"] += 1
        item["sources"].add((row["source_type"], row["source_id"]))
        if row["d"] and row["d"] >= week.isoformat():
            item["week"] += 1
        item["updated"] = max(item["updated"], row["d"] or "")
    levels = []
    for item in topics.values():
        sources = len(item.pop("sources"))
        rank, label = level(item["count"], sources)
        levels.append({**item, "sources": sources, "level": rank, "level_name": label})
    levels.sort(key=lambda item: (-item["level"], -item["count"], item["name"]))

    since = week.isoformat()
    def window(sql, *args):
        return db.execute(sql, (shift, since, *args)).fetchall()
    documents = window("SELECT name FROM files WHERE date(created,?)>=? ORDER BY created DESC")
    branches = window("SELECT id,name FROM branches WHERE date(created,?)>=? ORDER BY created DESC")
    mapping = projection(db)
    new_branches = [row["name"] for row in branches if mapping.get(row["id"], row["id"]) == row["id"]]
    added = window(f"""SELECT source_type,COUNT(*) AS n FROM ({EFFECTIVE})
        WHERE date(created,?)>=? GROUP BY source_type""")
    exams = window("""SELECT COUNT(*) AS n,MAX(quality_score) AS best FROM brain_lab_generations
        WHERE date(created,?)>=?""")[0]
    gaps = window("SELECT COUNT(*) AS n FROM brain_lab_gaps WHERE date(first_seen,?)>=?")[0]["n"]
    skills = window("""SELECT name,status FROM brain_lab_skills
        WHERE date(changed,?)>=? ORDER BY changed DESC""")
    by_source = {row["source_type"]: row["n"] for row in added}
    diary = {
        "since": since, "until": today.isoformat(),
        "knowledge": sum(by_source.values()), "from_chat": by_source.get("chat", 0),
        "documents": len(documents), "document_names": [row["name"] for row in documents[:5]],
        "branches": len(new_branches), "branch_names": new_branches[:8],
        "exams": exams["n"], "best_quality": exams["best"], "gaps": gaps,
        "skills": [dict(row) for row in skills[:6]],
        "top_topics": [{"name": item["name"], "week": item["week"]}
                       for item in sorted(levels, key=lambda item: -item["week"]) if item["week"]][:3],
    }
    return {"series": series, "diary": diary, "topics": levels}
