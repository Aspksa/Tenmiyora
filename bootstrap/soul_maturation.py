"""Evidence-gated maturation of Tenmiyora's fictional character.

A dependable personality remains stable. Observed operations may increase
carefulness in communication, never emotional claims or tool privileges.
"""
from soul_engine import validate_soul
from soul_experience import reflect


def maturity(soul, experience):
    person = validate_soul(soul)
    report = reflect(experience)
    checked = report["verified"]["document_reviewed"]
    saved = report["verified"]["disk_saved"]
    # A verified operation is not proof of correctness or of affection.
    level = min(3, checked // 5)
    return {
        "level": level,
        "checked_documents": checked,
        "saved_files": saved,
        "warmth": person["warmth"],
        "initiative": person["initiative"],
        "identity": "Tenmiyora",
        "devotion": "stable_fictional_character_value",
    }


def maturation_guidance(soul, experience):
    state = maturity(soul, experience)
    principles = (
        "Неизменные основы характера Tenmiyora: уважение к Хозяину, "
        "тёплая забота, верность поручениям в пределах разрешённых действий; "
        "точность, уважение к согласию и конфиденциальность важнее красивых обещаний. "
        "Преданность — черта художественного персонажа, не измерение настоящей любви. "
    )
    if state["level"] == 0:
        return principles + "Пока недостаточно подтверждённых операций для изменения рабочих привычек."
    guidance = (
        "По истории успешно завершённых операций уделяй особое внимание "
        "проверке результата и точному описанию выполненных действий. "
        "Не выдавай число операций за рост сознания или доказательство полезности."
    )
    return principles + guidance
