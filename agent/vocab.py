"""Vocabulary extraction and tiering for Exam Tutor.

Extracts English words from passage + question text, classifies them
against the national curriculum word list + user appearance history,
and returns a structured vocabulary_insight for the review page.
"""

import json
import re
from pathlib import Path


# ── Stopwords — common function words not worth tracking ──
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "i", "you", "he",
    "she", "it", "we", "they", "me", "him", "her", "us", "them", "my",
    "your", "his", "its", "our", "their", "mine", "yours", "hers", "ours",
    "theirs", "this", "that", "these", "those", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "like",
    "and", "but", "or", "so", "if", "because", "when", "where", "how",
    "what", "which", "who", "not", "no", "than", "then", "also", "very",
    "just", "now", "here", "there", "up", "down", "out", "off", "over",
    "under", "again", "more", "some", "any", "each", "every", "all",
    "both", "few", "many", "much", "such", "only", "other", "one", "two",
    "three", "first", "last", "new", "old", "good", "bad", "big", "small",
    "high", "low", "long", "short", "great", "little", "own", "same",
    "right", "left", "still", "back", "go", "get", "make", "know", "take",
    "see", "come", "think", "look", "want", "give", "use", "find", "tell",
    "ask", "work", "seem", "feel", "try", "leave", "call", "keep", "let",
    "begin", "show", "hear", "play", "run", "move", "live", "believe",
    "hold", "bring", "happen", "write", "sit", "stand", "lose", "pay",
    "meet", "set", "learn", "change", "lead", "understand", "watch",
    "follow", "stop", "create", "speak", "read", "spend", "grow", "open",
    "walk", "win", "teach", "offer", "remember", "consider", "appear",
    "buy", "wait", "serve", "die", "send", "build", "stay", "fall",
    "cut", "reach", "kill", "raise", "pass", "sell", "decide", "return",
    "explain", "hope", "develop", "carry", "break", "receive", "agree",
    "support", "hit", "produce", "eat", "cover", "catch", "draw", "choose",
}


def _load_curriculum() -> dict:
    """Load the curriculum word list: {word_lower: [pos, chinese]}."""
    path = Path(__file__).parent.parent / "data" / "vocab" / "curriculum_1600.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {k.lower(): v for k, v in raw.items()}


# Module-level cache
_CURRICULUM = None


def get_curriculum() -> dict:
    global _CURRICULUM
    if _CURRICULUM is None:
        _CURRICULUM = _load_curriculum()
    return _CURRICULUM


def extract_words(text: str) -> list[str]:
    """Extract unique lowercase English words from text, excluding stopwords."""
    if not text:
        return []
    # Match 2+ letter English words
    words = re.findall(r'[a-zA-Z]{2,}', text.lower())
    seen = set()
    result = []
    for w in words:
        if w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
    return result


def classify(
    words: list[str],
    curriculum: dict,
    history: dict,
) -> dict:
    """Classify words into high/medium/low frequency tiers.

    Tiers:
      high   — in curriculum AND appeared >= 3 times in history
      medium — in curriculum AND appeared < 3 times,
               OR not in curriculum but appeared >= 2 times
      low    — not in curriculum AND first appearance
               OR not in curriculum AND appeared only once before

    Returns: {tier: [{word, pos, chinese, count}]}
    """
    tiers = {"high": [], "medium": [], "low": []}

    for word in words:
        in_curriculum = word in curriculum
        hist = history.get(word)
        count = hist["appearance_count"] if hist else 0

        if in_curriculum:
            cur = curriculum[word]
            entry = {"word": word, "pos": cur[0], "chinese": cur[1], "count": count}

            if count >= 3:
                tiers["high"].append(entry)
            else:
                tiers["medium"].append(entry)
        else:
            # Not in curriculum — no POS/chinese from curriculum
            entry = {"word": word, "pos": "", "chinese": "", "count": count}

            if count >= 2:
                tiers["medium"].append(entry)
            else:
                tiers["low"].append(entry)

    # Sort each tier alphabetically
    for tier in tiers.values():
        tier.sort(key=lambda x: x["word"])

    return tiers


def process_vocabulary(
    text: str,
    exam_id: str,
    store,
) -> dict:
    """Full vocabulary pipeline: extract → lookup → classify → record → return.

    Args:
        text: Passage + question text to extract words from
        exam_id: Current exam ID (for recording appearances)
        store: ExamStore instance (for vocabulary lookups and recording)

    Returns:
        {"high": [...], "medium": [...], "low": [...]}
    """
    words = extract_words(text)
    if not words:
        return {"high": [], "medium": [], "low": []}

    curriculum = get_curriculum()
    history = store.vocab_lookup(words)

    # Record new appearances
    for word in words:
        cur = curriculum.get(word)
        if cur:
            store.vocab_record(word, cur[0], cur[1], exam_id)
        elif history.get(word):
            # Non-curriculum word with history — record with existing data
            store.vocab_record(word, history[word].get("pos", ""),
                              history[word].get("chinese", ""), exam_id)
        else:
            # New non-curriculum word — record without POS
            store.vocab_record(word, "", "", exam_id)

    return classify(words, curriculum, history)
