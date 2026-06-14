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
    # Articles
    "the", "a", "an",
    # Be / Have / Do
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    # Modals
    "will", "would", "shall", "should", "may", "might", "must", "can", "could",
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their",
    "mine", "yours", "hers", "ours", "theirs",
    "myself", "yourself", "himself", "herself", "itself",
    "ourselves", "yourselves", "themselves",
    # Demonstratives / Interrogatives
    "this", "that", "these", "those",
    "what", "which", "who", "whom", "whose",
    # Prepositions
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "onto", "about", "like", "up", "down", "out", "off",
    "over", "under", "between", "through", "during", "before", "after",
    "above", "below", "against", "within", "without", "toward", "towards", "upon",
    # Conjunctions
    "and", "but", "or", "so", "if", "because", "when", "where", "how",
    "although", "though", "while", "since", "until", "unless", "whether",
    "nor", "yet", "both", "either", "neither",
    # Negation
    "not", "no", "never", "none",
    # Quantifiers / Determiners
    "some", "any", "each", "every", "all", "few", "many", "much", "such",
    "more", "most", "less", "least", "several",
    "no", "none", "another", "other", "own", "same",
    # Cardinal numbers
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "hundred", "thousand", "million",
    # Ordinals
    "first", "last", "next",
    # Time/Place function adverbs
    "now", "then", "here", "there", "today", "tomorrow", "yesterday",
    "once", "twice", "again", "ever", "already", "still", "always",
    "often", "sometimes", "usually", "never", "also", "even", "only", "just",
    "very", "too", "quite", "rather", "really", "enough", "almost",
    "else", "however", "therefore", "thus", "furthermore", "please", "well",
    "than",
}

# ── Common irregular forms for junior-high English ──
# Maps inflected form → base form. Only includes forms likely to appear
# in exam texts and whose base form is in the curriculum.
_IRREGULAR = {
    # be
    "am": "be", "is": "are", "was": "be", "were": "be", "been": "be",
    # have
    "had": "have", "has": "have",
    # do
    "did": "do", "done": "do", "does": "do",
    # go
    "went": "go", "gone": "go", "goes": "go",
    # make
    "made": "make", "makes": "make",
    # take
    "took": "take", "taken": "take", "takes": "take",
    # come
    "came": "come", "comes": "come",
    # see
    "saw": "see", "seen": "see", "sees": "see",
    # know
    "knew": "know", "known": "know", "knows": "know",
    # get
    "got": "get", "gotten": "get", "gets": "get",
    # think
    "thought": "think", "thinks": "think",
    # say
    "said": "say", "says": "say",
    # tell
    "told": "tell", "tells": "tell",
    # find
    "found": "find", "finds": "find",
    # give
    "gave": "give", "given": "give", "gives": "give",
    # write
    "wrote": "write", "written": "write", "writes": "write",
    # read (past)
    "reads": "read",
    # speak
    "spoke": "speak", "spoken": "speak", "speaks": "speak",
    # buy
    "bought": "buy", "buys": "buy",
    # bring
    "brought": "bring", "brings": "bring",
    # teach
    "taught": "teach", "teaches": "teach",
    # build
    "built": "build", "builds": "build",
    # feel
    "felt": "feel", "feels": "feel",
    # keep
    "kept": "keep", "keeps": "keep",
    # leave
    "left": "leave", "leaves": "leave",
    # lose
    "lost": "lose", "loses": "lose",
    # meet
    "met": "meet", "meets": "meet",
    # pay
    "paid": "pay", "pays": "pay",
    # send
    "sent": "send", "sends": "send",
    # spend
    "spent": "spend", "spends": "spend",
    # win
    "won": "win", "wins": "win",
    # catch
    "caught": "catch", "catches": "catch",
    # sell
    "sold": "sell", "sells": "sell",
    # eat
    "ate": "eat", "eaten": "eat", "eats": "eat",
    # drink
    "drank": "drink", "drunk": "drink", "drinks": "drink",
    # run
    "ran": "run", "runs": "run",
    # sing
    "sang": "sing", "sung": "sing", "sings": "sing",
    # swim
    "swam": "swim", "swum": "swim", "swims": "swim",
    # fly
    "flew": "fly", "flown": "fly", "flies": "fly",
    # grow
    "grew": "grow", "grown": "grow", "grows": "grow",
    # draw
    "drew": "draw", "drawn": "draw", "draws": "draw",
    # throw
    "threw": "throw", "thrown": "throw", "throws": "throw",
    # blow
    "blew": "blow", "blown": "blow", "blows": "blow",
    # choose
    "chose": "choose", "chosen": "choose", "chooses": "choose",
    # break
    "broke": "break", "broken": "break", "breaks": "break",
    # forget
    "forgot": "forget", "forgotten": "forget", "forgets": "forget",
    # begin
    "began": "begin", "begun": "begin", "begins": "begin",
    # become
    "became": "become", "becomes": "become",
    # fall
    "fell": "fall", "fallen": "fall", "falls": "fall",
    # lie
    "lay": "lie", "lain": "lie", "lies": "lie", "lying": "lie",
    # mean
    "meant": "mean", "means": "mean",
    # wake
    "woke": "wake", "woken": "wake", "wakes": "wake",
    # ride
    "rode": "ride", "ridden": "ride", "rides": "ride",
    # rise
    "rose": "rise", "risen": "rise", "rises": "rise",
    # drive
    "drove": "drive", "driven": "drive", "drives": "drive",
    # wear
    "wore": "wear", "worn": "wear", "wears": "wear",
    # steal
    "stole": "steal", "stolen": "steal", "steals": "steal",
    # hide
    "hid": "hide", "hidden": "hide", "hides": "hide",
    # lead
    "led": "lead", "leads": "lead",
    # feed
    "fed": "feed", "feeds": "feed",
    # fight
    "fought": "fight", "fights": "fight",
    # hold
    "held": "hold", "holds": "hold",
    # learn
    "learnt": "learn", "learns": "learn",
    # lend
    "lent": "lend", "lends": "lend",
    # light
    "lit": "light", "lights": "light",
    # ring
    "rang": "ring", "rung": "ring", "rings": "ring",
    # shake
    "shook": "shake", "shaken": "shake", "shakes": "shake",
    # shut
    "shuts": "shut",
    # sleep
    "slept": "sleep", "sleeps": "sleep",
    # smell
    "smelt": "smell", "smells": "smell",
    # stand
    "stood": "stand", "stands": "stand",
    # sweep
    "swept": "sweep", "sweeps": "sweep",
    # sit
    "sat": "sit", "sits": "sit",
    # stick
    "stuck": "stick", "sticks": "stick",
    # strike
    "struck": "strike", "strikes": "strike",
    # understand
    "understood": "understand", "understands": "understand",
    # Irregular plurals
    "children": "child",
    "men": "man", "women": "woman",
    "teeth": "tooth", "feet": "foot",
    "mice": "mouse", "geese": "goose",
    "lives": "life", "knives": "knife",
    "wives": "wife", "wolves": "wolf",
    "halves": "half", "selves": "self",
    "shelves": "shelf",
    # Irregular comparatives
    "better": "good", "best": "good",
    "worse": "bad", "worst": "bad",
    "more": "many", "most": "many",
    "less": "little", "least": "little",
    "older": "old", "oldest": "old",
    "younger": "young", "youngest": "young",
}


def _suffix_lemmatize(word: str) -> list[str]:
    """Generate candidate base forms by stripping common English suffixes.

    Returns ordered list of candidates — caller checks curriculum match.
    """
    candidates = []

    # -ies → -y (tries→try, countries→country)
    if word.endswith("ies") and len(word) > 4:
        candidates.append(word[:-3] + "y")

    # -ves → -f / -fe (saves→safe? No, leaves→leaf)
    if word.endswith("ves") and len(word) > 4:
        candidates.append(word[:-3] + "f")
        candidates.append(word[:-3] + "fe")

    # -es after s/x/z/ch/sh (watches→watch, boxes→box)
    if word.endswith("es") and len(word) > 4:
        stem = word[:-2]
        if stem.endswith(("ch", "sh", "s", "x", "z")):
            candidates.append(stem)
        # -es after consonant+o (goes→go, does→do)
        elif len(stem) >= 2 and stem[-1] == "o" and stem[-2] not in "aeiou":
            candidates.append(stem)

    # -ing → base + optional doubled consonant
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        candidates.append(stem)  # playing→play
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            candidates.append(stem[:-1])  # sitting→sit

    # -ed → base + optional doubled consonant
    if word.endswith("ed") and len(word) > 4:
        stem = word[:-2]
        candidates.append(stem)  # played→play
        candidates.append(word[:-1])  # liked→like
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            candidates.append(stem[:-1])  # stopped→stop

    # -er/-est → base
    for sfx in ("er", "est"):
        if word.endswith(sfx) and len(word) > len(sfx) + 2:
            stem = word[:-len(sfx)]
            candidates.append(stem)
            if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
                candidates.append(stem[:-1])  # bigger→big

    # -s (most common: plural nouns, 3rd person verbs)
    if word.endswith("s") and len(word) > 3:
        if not word.endswith(("ss", "us", "is", "os")):
            candidates.append(word[:-1])  # ways→way, scientists→scientist

    # -ly (adverb → adjective)
    if word.endswith("ly") and len(word) > 4:
        stem = word[:-2]
        candidates.append(stem)
        if stem.endswith("i"):
            candidates.append(stem[:-1] + "y")  # happily→happy

    # -ment / -tion / -ness / -ship / -ence / -ance (derived nouns)
    for sfx in ("ment", "tion", "ness", "ship", "ence", "ance", "able", "ible"):
        if word.endswith(sfx) and len(word) > len(sfx) + 3:
            candidates.append(word[:-len(sfx)])

    return candidates


def _build_lemma_map(curriculum: dict) -> dict:
    """Build mapping from inflected/derived forms → curriculum base word.

    Only returns mappings where the candidate base form IS in the curriculum.
    This ensures 'means' maps to 'mean' (in curriculum), but 'tables' doesn't
    map to anything if 'table' is not in the curriculum.
    """
    mapping = {}
    for base in curriculum:
        # Always map the base to itself
        mapping[base] = base

        # Regular inflections
        forms = [
            base + "s",       # nouns/verbs
            base + "es",      # after s/x/z/ch/sh
            base + "ing",     # gerund
            base + "ed",      # past
            base + "er",      # comparative / agent noun
            base + "est",     # superlative
            base + "ly",      # adverb
            base + "ment",    # derived noun
            base + "ness",    # derived noun
        ]
        if base.endswith("e"):
            forms.extend([
                base + "s", base + "d", base[:-1] + "ing",
                base + "r", base + "st",
            ])
        if base.endswith("y") and len(base) > 2 and base[-2] not in "aeiou":
            forms.extend([
                base[:-1] + "ies", base[:-1] + "ied",
            ])
        if len(base) >= 2 and base[-1] not in "aeiou" and base[-2] in "aeiou" and base[-1] not in "wyx":
            # CVC pattern → double final consonant
            double = base + base[-1]
            forms.extend([double + "ing", double + "ed", double + "er", double + "est"])

        for f in forms:
            if f not in mapping:
                mapping[f] = base

    # Irregulars override regular
    mapping.update(_IRREGULAR)

    return mapping


# Module-level cache
_LEMMA_MAP = None


def _get_lemma_map() -> dict:
    global _LEMMA_MAP
    if _LEMMA_MAP is None:
        _LEMMA_MAP = _build_lemma_map(get_curriculum())
    return _LEMMA_MAP


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
    """Extract unique normalized English words from text, excluding stopwords.

    Normalizes inflected forms to base forms using the lemma map
    (e.g., scientists→scientist, protecting→protect, ways→way).
    Only normalizes to a base form if the base is in the curriculum.
    """
    if not text:
        return []
    words = re.findall(r'[a-zA-Z]{2,}', text.lower())
    lemma = _get_lemma_map()
    seen = set()
    result = []
    for w in words:
        if w in _STOPWORDS:
            continue
        base = lemma.get(w, w)
        if base not in seen:
            seen.add(base)
            result.append(base)
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
    user_id: str = "",
) -> dict:
    """Full vocabulary pipeline: extract → normalize → record → classify → return.

    Records all words BEFORE classifying — so the current exam's appearance
    counts toward tier placement (3rd appearance = high, not medium).
    """
    words = extract_words(text)
    if not words:
        return {"high": [], "medium": [], "low": []}

    curriculum = get_curriculum()

    # 1. Record all new appearances first
    for word in words:
        cur = curriculum.get(word)
        if cur:
            store.vocab_record(word, cur[0], cur[1], exam_id, user_id=user_id)
        else:
            # Look up existing data from history
            history_snapshot = store.vocab_lookup([word], user_id=user_id)
            hist = history_snapshot.get(word, {})
            store.vocab_record(word, hist.get("pos", ""),
                              hist.get("chinese", ""), exam_id)

    # 2. Now classify with updated counts (includes current exam)
    history = store.vocab_lookup(words)
    return classify(words, curriculum, history)
