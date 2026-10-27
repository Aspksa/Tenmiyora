"""Auditable error patterns and habit quality gates for Tenmiyora.

Only explicit user-recorded episodes can contribute to subjective outcomes.
Evidence is retained as counts, not invented introspection.
"""
from collections import Counter
from soul_experience import validate_experience, APPROACHES


def assess(state):
    data = validate_experience(state)
    totals = {name: {"success": 0, "error": 0} for name in sorted(APPROACHES)}
    repeated = Counter()
    for item in data["episodes"]:
        summary = item["summary"]
        kind = item["kind"]
        if kind == "error":
            repeated[summary] += 1
        for name in totals:
            if name in summary and kind in ("success", "error"):
                totals[name][kind] += 1
    accepted = []
    rejected = []
    for name, counts in totals.items():
        successes, errors = counts["success"], counts["error"]
        # 3 distinct confirmed positive episodes; success rate >= 75%.
        if successes >= 3 and successes >= 3 * errors:
            accepted.append(name)
        elif errors >= 2 and errors >= successes:
            rejected.append(name)
    return {
        "accepted": accepted,
        "discouraged": rejected,
        "repeated_errors": [
            {"summary": summary, "count": count}
            for summary, count in sorted(repeated.items())
            if count >= 2
        ][:5],
        "evidence": totals,
    }


def quality_guidance(state):
    result = assess(state)
    if not result["accepted"] and not result["discouraged"]:
        return ""
    # No raw episode content is sent to the provider.
    good = ", ".join(result["accepted"]) or "нет"
    bad = ", ".join(result["discouraged"]) or "нет"
    return ("Анализ оценок Хозяина, без доказательства независимой проверки: "
            "устойчиво поддерживаемые подходы: " + good
            + "; подходы, требующие пересмотра: " + bad
            + ". Применяй их с учётом текущей задачи, а не как безусловные правила.")
