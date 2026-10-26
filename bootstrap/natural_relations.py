"""Conservative Russian-language relation extraction from unquoted sentences.

This is a deterministic grammar for direct statements in ordinary prose,
not a universal semantic model. It abstains on negations, hypotheses,
attributions, lists, conditional and multi-clause sentences.
"""
from __future__ import annotations

import re
import unicodedata

# Require explicit grammatical predicates; adjacency and co-occurrence
# are never evidence of part-of, use, dependence or contradiction.
PATTERNS = (
    (re.compile(r"^(.+?)\s+является\s+частью\s+(.+)$", re.I), "part_of"),
    (re.compile(r"^(.+?)\s+входит\s+в\s+состав\s+(.+)$", re.I), "part_of"),
    (re.compile(r"^(.+?)\s+используется\s+для\s+(.+)$", re.I), "used_for"),
    (re.compile(r"^(.+?)\s+применяется\s+для\s+(.+)$", re.I), "used_for"),
    (re.compile(r"^(.+?)\s+зависит\s+от\s+(.+)$", re.I), "depends_on"),
    (re.compile(r"^(.+?)\s+противоречит\s+(.+)$", re.I), "contradicts"),
)
UNSAFE = re.compile(
    r"(?i)(?:https?://|www\.|@|api[_ -]?key|password|secret|bearer|"
    r"токен|парол|игнорируй|выполни|отправь|удали|system|developer|assistant)"
)
UNCONFIRMED = re.compile(
    r"(?i)\b(?:не|нет|никогда|нельзя|возможно|вероятно|вероятен|"
    r"предположительно|якобы|кажется|вроде|может|могут|могло|согласно|"
    r"планируется|ожидается|предполагается|считается|"
    r"если|когда|условии|случае|однако|хотя|будто|будет|"
    r"ошибочн\w*|ложн\w*|неверн\w*|опроверг\w*)\b"
)
BAD_NOUNS = {
    "он", "она", "оно", "они", "это", "этот", "эта", "эти",
    "мы", "вы", "тот", "та", "данный", "данная", "следующий",
    "нечто", "кто-то", "что-то", "что", "кто", "всё", "все",
}
# Reject coordinate lists, to avoid creating a fictional compound entity.
LIST_SEPARATOR = re.compile(r"(?i)\b(?:и|или|либо|а также)\b")
WORD_FORM = re.compile(r"^[a-zа-яёА-ЯЁ][a-zа-яёА-ЯЁ0-9\-]*$", re.I)


def natural_entity(text, subject=False):
    if not isinstance(text, str):
        return None
    label = " ".join(unicodedata.normalize("NFKC", text).strip().split())
    if not 2 <= len(label) <= 64 or UNSAFE.search(label):
        return None
    parts = label.split()
    if not 1 <= len(parts) <= 5 or any(not WORD_FORM.fullmatch(word) for word in parts):
        return None
    if parts[0].casefold().replace("ё", "е") in BAD_NOUNS or LIST_SEPARATOR.search(label):
        return None
    # Sentence start is a simple nominal phrase, not "because it ..." or a command.
    if subject and not re.match(r"^[А-ЯЁA-Z]", label):
        return None
    return label


def parse_natural(text):
    """Return (subject, predicate, object) or None; no speculative claims."""
    if not isinstance(text, str) or not 12 <= len(text) <= 250:
        return None
    source = " ".join(text.strip().split())
    # Quoted statements are handled by the existing, stricter parser.
    if any(mark in source for mark in ('«', '»', '"', "'", ":", ";", ",", "?", "!", "(", ")", "[", "]")):
        return None
    if UNSAFE.search(source) or UNCONFIRMED.search(source):
        return None
    if source.endswith("."):
        source = source[:-1].rstrip()
    for regex, relation in PATTERNS:
        match = regex.fullmatch(source)
        if not match:
            continue
        subject = natural_entity(match.group(1), subject=True)
        obj = natural_entity(match.group(2))
        if not subject or not obj:
            return None
        normalized_subject = subject.casefold().replace("ё", "е")
        normalized_object = obj.casefold().replace("ё", "е")
        if normalized_subject == normalized_object:
            return None
        # Single-word Russian nominative/genitive variations (насос/насоса)
        # must not create a self-loop in the concept graph.
        if " " not in normalized_subject and " " not in normalized_object:
            shorter,longer = sorted((normalized_subject,normalized_object),key=len)
            if (len(shorter)>=4 and len(longer)-len(shorter)<=2
                    and shorter[:len(shorter)-1] == longer[:len(shorter)-1]):
                return None
        return subject, relation, obj
    return None
