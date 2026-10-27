"""Рост Мозга для интерфейса: график по дням, дневник недели, уровни тем.

Только чтение SQLite. Знания считаются так же, как в дереве веток:
knowledge_items, а для веток без них — старые facts.
"""
from datetime import date, timedelta

from source_provenance import group_sources
from topic_aliases import projection

EFFECTIVE = """SELECT branch_id AS branch,source_type,source_id,created FROM knowledge_items
    UNION ALL
    SELECT f.branch,f.source_type,f.source_id,f.created FROM facts f WHERE NOT EXISTS
      (SELECT 1 FROM knowledge_items k WHERE k.branch_id=f.branch)"""

LEVELS = ((1, "Начальный"), (2, "Растущий"), (3, "Уверенный"), (4, "Глубокий"))
# Что нужно теме для следующего уровня: (знаний, независимых источников).
NEEDS = {1: (5, 1), 2: (15, 2), 3: (40, 3)}
# Уровень всего Мозга растёт с общим числом знаний.
BRAIN_LEVELS = ((0, "Искра"), (10, "Первые нейроны"), (25, "Сеть"), (50, "Кора"), (100, "Память"),
                (200, "Опыт"), (400, "Мудрость"), (800, "Глубина"), (1600, "Разум"))
SPARK_DAYS = 14


def level(count, sources):
    """Грубая шкала: объём знаний и число независимых источников."""
    if count < 5:
        return LEVELS[0]
    if count < 15 or sources < 2:
        return LEVELS[1]
    if count < 40 or sources < 3:
        return LEVELS[2]
    return LEVELS[3]


def next_step(rank, count, sources):
    """Сколько не хватает теме до следующего уровня; None — уровень наивысший."""
    if rank not in NEEDS:
        return None
    need_count, need_sources = NEEDS[rank]
    progress = min(count / need_count, sources / need_sources, 1)
    return {"name": LEVELS[rank][1], "count": max(0, need_count - count),
            "sources": max(0, need_sources - sources), "progress": round(progress, 3)}


def brain_level(total):
    """Общий уровень Мозга и путь до следующего."""
    rank = max(i for i, (floor, _) in enumerate(BRAIN_LEVELS) if total >= floor)
    floor, name = BRAIN_LEVELS[rank]
    item = {"level": rank + 1, "name": name, "total": total, "floor": floor}
    if rank + 1 < len(BRAIN_LEVELS):
        nxt, nxt_name = BRAIN_LEVELS[rank + 1]
        item.update(next=nxt, next_name=nxt_name, progress=round((total - floor) / (nxt - floor), 3))
    else:
        item.update(next=None, next_name=None, progress=1)
    return item


def streak(series):
    """Дней подряд с новыми знаниями; пустой сегодняшний день серию ещё не рвёт."""
    days = [day["added"] for day in series]
    if days and not days[-1]:
        days.pop()
    count = 0
    for added in reversed(days):
        if not added:
            break
        count += 1
    return count


def independent_sources(db, sources):
    """Копии и заимствования одного документа — один источник; весь чат — один."""
    files = [{"source_id": source_id} for kind, source_id in sources if kind == "file"]
    groups, _ = group_sources(db, files)
    return len(groups) + any(kind != "file" for kind, _ in sources)


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
    visible = projection(db)
    topics, fresh = {}, {}
    spark_from = today - timedelta(days=SPARK_DAYS - 1)
    for row in db.execute(f"SELECT branch,source_type,source_id,date(created,?) AS d FROM ({EFFECTIVE})", (shift,)):
        if row["d"] and row["d"] >= week.isoformat():
            target = visible.get(row["branch"], row["branch"])
            fresh[target] = fresh.get(target, 0) + 1
        root = roots.get(row["branch"])
        if not root:
            continue
        item = topics.setdefault(root[0], {"id": root[0], "name": root[1], "count": 0,
                                           "sources": set(), "week": 0, "updated": "",
                                           "spark": [0] * SPARK_DAYS})
        item["count"] += 1
        if row["d"] and row["d"] >= spark_from.isoformat():
            index = (date.fromisoformat(row["d"]) - spark_from).days
            if 0 <= index < SPARK_DAYS:
                item["spark"][index] += 1
        item["sources"].add((row["source_type"], row["source_id"]))
        if row["d"] and row["d"] >= week.isoformat():
            item["week"] += 1
        item["updated"] = max(item["updated"], row["d"] or "")
    levels = []
    for item in topics.values():
        sources = independent_sources(db, item.pop("sources"))
        rank, label = level(item["count"], sources)
        levels.append({**item, "sources": sources, "level": rank, "level_name": label,
                       "next": next_step(rank, item["count"], sources)})
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
    diary["days"] = diary_days(db, shift, since, mapping)
    total = series[-1]["total"] if series else 0
    best = max(series, key=lambda day: day["added"]) if series else None
    brain = {**brain_level(total), "week": diary["knowledge"], "streak": streak(series),
             "best_day": best if best and best["added"] else None, "topics": len(levels)}
    # Прирост за неделю по видимым веткам — для подсветки на карте знаний.
    return {"series": series, "diary": diary, "topics": levels, "branches_week": fresh, "brain": brain}


def diary_days(db, shift, since, mapping):
    """Дневник по дням недели: что Мозг узнал и что сделал сам, новые дни сверху."""
    days = {}

    def day(d):
        return days.setdefault(d, {"date": d, "knowledge": 0, "chat": 0, "documents": [],
                                   "branches": [], "self": [], "exam": None})
    for row in db.execute(f"""SELECT date(created,?) AS d,source_type,COUNT(*) AS n FROM ({EFFECTIVE})
            WHERE date(created,?)>=? GROUP BY d,source_type""", (shift, shift, since)):
        item = day(row["d"])
        item["knowledge"] += row["n"]
        if row["source_type"] == "chat":
            item["chat"] += row["n"]
    for row in db.execute("SELECT date(created,?) AS d,name FROM files WHERE date(created,?)>=? ORDER BY created",
                          (shift, shift, since)):
        day(row["d"])["documents"].append(row["name"])
    for row in db.execute("SELECT date(created,?) AS d,id,name FROM branches WHERE date(created,?)>=? ORDER BY created",
                          (shift, shift, since)):
        if mapping.get(row["id"], row["id"]) == row["id"]:
            day(row["d"])["branches"].append(row["name"])
    for row in db.execute("""SELECT date(created,?) AS d,MAX(quality_score) AS q FROM brain_lab_generations
            WHERE date(created,?)>=? GROUP BY d""", (shift, shift, since)):
        day(row["d"])["exam"] = row["q"]
    for row in db.execute("""SELECT date(time,?) AS d,task,summary FROM brain_idle_log
            WHERE date(time,?)>=? ORDER BY id""", (shift, shift, since)):
        day(row["d"])["self"].append({"task": row["task"], "summary": row["summary"]})
    result = []
    for d in sorted(days, reverse=True):
        item = days[d]
        item["documents"] = item["documents"][:6]
        item["branches"] = item["branches"][:8]
        item["self"] = item["self"][-4:]
        result.append(item)
    return result
