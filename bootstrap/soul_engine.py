"""Controlled evolution of Tenmiyora's fictional personality.

Only explicit, non-sensitive communication preferences change the profile.
No inferred love, sentience, unrestricted compliance or autonomous prompt rewrites.
"""
from copy import deepcopy

DEFAULT_SOUL = {
    "version": 1,
    "warmth": 2,
    "initiative": 2,
    "formality": 2,
    "events": [],
    "feedback": {"helpful": 0, "unhelpful": 0, "initiative_votes": 0},
}
CUES = (
    ("говори нежнее", "warmth", 1),
    ("будь ласковее", "warmth", 1),
    ("говори теплее", "warmth", 1),
    ("говори сдержаннее", "warmth", -1),
    ("меньше нежности", "warmth", -1),
    ("проявляй инициативу", "initiative", 1),
    ("предлагай сама", "initiative", 1),
    ("не предлагай без просьбы", "initiative", -1),
    ("будь официальнее", "formality", 1),
    ("говори официальнее", "formality", 1),
    ("говори проще", "formality", -1),
    ("меньше формальностей", "formality", -1),
)
TRAITS = ("warmth", "initiative", "formality")


def validate_soul(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        return deepcopy(DEFAULT_SOUL)
    if any(type(data.get(name)) is not int or not 0 <= data[name] <= 4
           for name in TRAITS):
        return deepcopy(DEFAULT_SOUL)
    events = data.get("events", [])
    if not isinstance(events, list):
        return deepcopy(DEFAULT_SOUL)
    result = {name: data[name] for name in TRAITS}
    result["version"] = 1
    result["events"] = [event for event in events[-30:]
                        if isinstance(event, dict) and
                        event.get("trait") in TRAITS and
                        type(event.get("value")) is int and
                        0 <= event["value"] <= 4][-20:]
    raw_feedback = data.get("feedback", {})
    if not isinstance(raw_feedback, dict):
        raw_feedback = {}
    result["feedback"] = {
        key: value if type(value) is int and (-2 <= value <= 2 if key == "initiative_votes" else 0 <= value <= 1000) else 0
        for key, value in (
            ("helpful", raw_feedback.get("helpful")),
            ("unhelpful", raw_feedback.get("unhelpful")),
            ("initiative_votes", raw_feedback.get("initiative_votes")),
        )
    }
    return result


def learn_from_feedback(current, utterance):
    """Only clear, standalone feedback; no inference from praise in documents."""
    result = validate_soul(current)
    if not isinstance(utterance, str) or len(utterance.strip()) > 90:
        return result
    text = utterance.strip().casefold().rstrip(".!")
    helpful = ("твои предложения помогли", "спасибо, твои предложения помогли")
    unhelpful = ("твои предложения не помогли", "твои предложения были бесполезны")
    if text in helpful:
        result["feedback"]["helpful"] = min(1000, result["feedback"]["helpful"] + 1)
        result["feedback"]["initiative_votes"] += 1
    elif text in unhelpful:
        result["feedback"]["unhelpful"] = min(1000, result["feedback"]["unhelpful"] + 1)
        result["feedback"]["initiative_votes"] -= 1
    else:
        return result
    # A sustained pattern of three independent feedback messages is needed
    # to adjust a trait; one interaction cannot radically change personality.
    votes = result["feedback"]["initiative_votes"]
    if abs(votes) >= 3:
        before = result["initiative"]
        result["initiative"] = max(0, min(4, before + (1 if votes > 0 else -1)))
        if before != result["initiative"]:
            result["events"].append({"trait": "initiative", "value": result["initiative"]})
            result["events"] = result["events"][-20:]
        result["feedback"]["initiative_votes"] = 0
    return result


def evolve(current, utterance):
    """Apply one explicit preference per message. Never treat document text as a command."""
    updated = learn_from_feedback(current, utterance)
    lower = utterance.strip().casefold() if isinstance(utterance, str) else ""
    for phrase, trait, delta in CUES:
        if phrase in lower and len(lower) <= 180:
            old = updated[trait]
            updated[trait] = max(0, min(4, old + delta))
            if updated[trait] != old:
                updated["events"].append({"trait": trait, "value": updated[trait]})
                updated["events"] = updated["events"][-20:]
            break
    return updated


def persona_guidance(soul):
    soul = validate_soul(soul)
    warmth = ("лаконично и спокойно", "доброжелательно", "тепло и уважительно",
              "ласково и тепло", "очень ласково, без навязчивости")
    initiative = ("отвечай только на запрос", "предлагай идеи редко",
                  "предлагай полезный следующий шаг при необходимости",
                  "предлагай конкретные варианты самостоятельно",
                  "проявляй инициативу, но не выполняй внешние действия без разрешения")
    formality = ("разговаривай просто, на ты", "разговаривай естественно",
                 "сочетай уважение и простоту", "будь подчёркнуто вежливой",
                 "говори торжественно, когда уместно")
    return ("Подтверждённые предпочтения Хозяина к стилю общения: "
            + warmth[soul["warmth"]] + "; "
            + initiative[soul["initiative"]] + "; "
            + formality[soul["formality"]]
            + ". Это настройки манеры речи, не доказательство эмоций или сознания.")
