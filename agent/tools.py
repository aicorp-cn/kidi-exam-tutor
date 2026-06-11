"""Tool Definitions for DeepSeek Strict Tool Calling.

All 5 tools are defined here as Python dicts — pure data, no logic.
Used by engine.py for both Strict Mode (beta endpoint) and fallback mode.
"""

# ═══════════════════════════════════════════════════════════════
# Stage 1: Parse Exam
# ═══════════════════════════════════════════════════════════════

PARSE_EXAM_DEF = {
    "type": "function",
    "function": {
        "name": "parse_exam",
        "strict": True,
        "description": (
            "Parse OCR text of an English exam into structured JSON. "
            "Identify the exam type, extract the full passage, and list all questions "
            "with their context and options. For non-applicable fields, use empty strings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "exam_type": {
                    "type": "string",
                    "enum": ["grammar_cloze", "cloze", "reading_comp", "true_false"],
                    "description": "The type of exam detected",
                },
                "passage": {
                    "type": "string",
                    "description": "The full passage text extracted from the exam",
                },
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "integer",
                                "description": "Question number, starting from 1",
                            },
                            "context_before": {
                                "type": "string",
                                "description": "1-2 sentences before the blank or key sentence",
                            },
                            "sentence_with_blank": {
                                "type": "string",
                                "description": "The sentence containing ___N___ (for cloze types). Empty string for reading_comp and true_false.",
                            },
                            "context_after": {
                                "type": "string",
                                "description": "1-2 sentences after the blank or key sentence",
                            },
                            "options": {
                                "type": "object",
                                "description": "A-D options. For true_false, all values are empty strings.",
                                "properties": {
                                    "A": {"type": "string"},
                                    "B": {"type": "string"},
                                    "C": {"type": "string"},
                                    "D": {"type": "string"},
                                },
                                "required": ["A", "B", "C", "D"],
                                "additionalProperties": False,
                            },
                            "stem": {
                                "type": "string",
                                "description": "Question stem for reading_comp. Empty string for other types.",
                            },
                            "statement": {
                                "type": "string",
                                "description": "Statement for true_false. Empty string for other types.",
                            },
                        },
                        "required": [
                            "id", "context_before", "sentence_with_blank",
                            "context_after", "options", "stem", "statement",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["exam_type", "passage", "questions"],
            "additionalProperties": False,
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# Stage 2: Generate Grammar Cloze
# ═══════════════════════════════════════════════════════════════

GENERATE_GRAMMAR_CLOZE_DEF = {
    "type": "function",
    "function": {
        "name": "generate_grammar_cloze",
        "strict": True,
        "description": (
            "Generate tutorial for grammar cloze exam. For each question, produce exactly 6 modules:\n\n"
            "1. 上下文 (Context): 1-2 sentences before the blank + the sentence with the correct answer "
            "in <u>underline</u> + 1-2 sentences after.\n\n"
            "2. 生词洞察 (Vocabulary): Each line as 'word ／DJ_phonetics／ Chinese_meaning'. "
            "Prioritize high-frequency exam words. Mark stress with \u02c8 on multi-syllable words.\n\n"
            "3. 选项词义 (Option Meanings): List ALL four options as 'A. word ／phonetics／ meaning', 'B. ...' etc.\n\n"
            "4. 考点 (Key Point): A short formula using explicit patterns, not grammar terminology. "
            "Example: '\u770b\u5230than\u2192\u9009\u6bd4\u8f83\u7ea7', 'while+\u8fdb\u884c\u65f6', 'many+\u590d\u6570\u540d\u8bcd'.\n\n"
            "5. 解析 (Analysis): 1-2 conversational Chinese sentences explaining why this answer is correct "
            "in the given context. Connect to what comes before and after the blank.\n\n"
            "6. 排除法 (Elimination): For each WRONG option (3 total), one line as "
            "'\u274c \u4e0d\u9009 X: specific_reason'. Reasons must point to grammar errors, "
            "collocation errors, or logical contradictions — never vague."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "number": {
                                "type": "integer",
                                "description": "Question number, matching the input",
                            },
                            "answer": {
                                "type": "string",
                                "enum": ["A", "B", "C", "D"],
                                "description": "The correct option letter",
                            },
                            "modules": {
                                "type": "object",
                                "properties": {
                                    "\u4e0a\u4e0b\u6587": {
                                        "type": "string",
                                        "description": "Context with answer in <u>underline</u>",
                                    },
                                    "\u751f\u8bcd\u6d1e\u5bdf": {
                                        "type": "string",
                                        "description": "Vocabulary: word ／DJ_phonetics／ meaning per line",
                                    },
                                    "\u9009\u9879\u8bcd\u4e49": {
                                        "type": "string",
                                        "description": "All four options: A. word ／phonetics／ meaning",
                                    },
                                    "\u8003\u70b9": {
                                        "type": "string",
                                        "description": "Explicit formula, not grammar terminology",
                                    },
                                    "\u89e3\u6790": {
                                        "type": "string",
                                        "description": "1-2 conversational Chinese sentences",
                                    },
                                    "\u6392\u9664\u6cd5": {
                                        "type": "string",
                                        "description": "\u274c \u4e0d\u9009 X: reason for each wrong option",
                                    },
                                },
                                "required": [
                                    "\u4e0a\u4e0b\u6587", "\u751f\u8bcd\u6d1e\u5bdf",
                                    "\u9009\u9879\u8bcd\u4e49", "\u8003\u70b9",
                                    "\u89e3\u6790", "\u6392\u9664\u6cd5",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["number", "answer", "modules"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# Stage 2: Generate Cloze (identical schema, separate name for routing)
# ═══════════════════════════════════════════════════════════════

GENERATE_CLOZE_DEF = {
    "type": "function",
    "function": {
        "name": "generate_cloze",
        "strict": True,
        "description": (
            "Generate tutorial for cloze exam. For each question, produce exactly 6 modules:\n\n"
            "1. 上下文 (Context): 1-2 sentences before the blank + the sentence with the correct answer "
            "in <u>underline</u> + 1-2 sentences after.\n\n"
            "2. 生词洞察 (Vocabulary): Each line as 'word ／DJ_phonetics／ Chinese_meaning'. "
            "Prioritize high-frequency exam words. Mark stress with \u02c8 on multi-syllable words.\n\n"
            "3. 选项词义 (Option Meanings): List ALL four options as 'A. word ／phonetics／ meaning', 'B. ...' etc.\n\n"
            "4. 考点 (Key Point): A short formula using explicit patterns, not grammar terminology. "
            "Example: '\u770b\u5230than\u2192\u9009\u6bd4\u8f83\u7ea7', 'while+\u8fdb\u884c\u65f6', 'many+\u590d\u6570\u540d\u8bcd'.\n\n"
            "5. 解析 (Analysis): 1-2 conversational Chinese sentences explaining why this answer is correct "
            "in the given context. Connect to what comes before and after the blank.\n\n"
            "6. 排除法 (Elimination): For each WRONG option (3 total), one line as "
            "'\u274c \u4e0d\u9009 X: specific_reason'. Reasons must point to grammar errors, "
            "collocation errors, or logical contradictions \u2014 never vague."
        ),
        "parameters": GENERATE_GRAMMAR_CLOZE_DEF["function"]["parameters"],
    },
}

# ═══════════════════════════════════════════════════════════════
# Stage 2: Generate Open Cloze (no preset options — infer answer)
# ═══════════════════════════════════════════════════════════════

GENERATE_OPEN_CLOZE_DEF = {
    "type": "function",
    "function": {
        "name": "generate_open_cloze",
        "strict": True,
        "description": (
            "Generate tutorial for open-ended cloze exam (no preset options). "
            "For each question, produce exactly 5 modules:\n\n"
            "1. 上下文 (Context): 1-2 sentences before the blank + the sentence with the "
            "inferred answer in <u>underline</u> + 1-2 sentences after.\n\n"
            "2. 生词洞察 (Vocabulary): Each line as 'word ／DJ_phonetics／ Chinese_meaning'. "
            "Prioritize high-frequency exam words. Mark stress with \u02c8 on multi-syllable words.\n\n"
            "3. 考点 (Inference Basis): Explain the reasoning that leads to this answer. "
            "Use patterns like '\u524d\u6587\u63d0\u5230X\u2192\u6b64\u5904\u5e94\u586bY', "
            "'\u56fa\u5b9a\u642d\u914dZ+\u6b64\u5904', "
            "'\u6839\u636e\u65f6\u6001\u6807\u5fd7\u2192\u52a8\u8bcd\u5f62\u5f0f\u4e3aY'.\n\n"
            "4. 解析 (Analysis): 1-2 conversational Chinese sentences explaining why this "
            "answer fits the context. Connect to what comes before and after the blank.\n\n"
            "5. 推断思路 (Deduction Path): 1-2 sentences explaining why other possible "
            "words are ruled out. Consider grammar, collocation, and semantic fit. "
            "Format: '\u6392\u9664\\u2026\u2026\uff0c\u56e0\u4e3a\\u2026\u2026'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "number": {
                                "type": "integer",
                                "description": "Question number, matching the input",
                            },
                            "answer": {
                                "type": "string",
                                "description": "The inferred word/phrase to fill in the blank",
                            },
                            "modules": {
                                "type": "object",
                                "properties": {
                                    "\u4e0a\u4e0b\u6587": {
                                        "type": "string",
                                        "description": "Context with answer in <u>underline</u>",
                                    },
                                    "\u751f\u8bcd\u6d1e\u5bdf": {
                                        "type": "string",
                                        "description": "Vocabulary: word ／DJ_phonetics／ meaning per line",
                                    },
                                    "\u8003\u70b9": {
                                        "type": "string",
                                        "description": "Inference basis: why this answer follows from context",
                                    },
                                    "\u89e3\u6790": {
                                        "type": "string",
                                        "description": "1-2 conversational Chinese sentences",
                                    },
                                    "\u63a8\u65ad\u601d\u8def": {
                                        "type": "string",
                                        "description": "Why other possible words are ruled out",
                                    },
                                },
                                "required": [
                                    "\u4e0a\u4e0b\u6587", "\u751f\u8bcd\u6d1e\u5bdf",
                                    "\u8003\u70b9", "\u89e3\u6790", "\u63a8\u65ad\u601d\u8def",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["number", "answer", "modules"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# Stage 2: Generate Reading Comprehension
# ═══════════════════════════════════════════════════════════════

GENERATE_READING_COMP_DEF = {
    "type": "function",
    "function": {
        "name": "generate_reading_comp",
        "strict": True,
        "description": (
            "Generate tutorial for reading comprehension exam. For each question, produce exactly 5 modules:\n\n"
            "1. 题干定位 (Passage Location): Quote the paragraph and sentence where the answer is found. "
            "Format: '\u539f\u6587\u7b2cX\u6bb5\uff1a\"...<u>key sentence</u>...\"'.\n\n"
            "2. 选项词义 (Option Meanings): Chinese translation with key words for ALL four options. "
            "Format: 'A. \u7ffb\u8bd1 \u2192 \u5173\u952e\u8bcd'.\n\n"
            "3. 考点 (Key Point): Identify question type and give its solution formula: "
            "\u7ec6\u8282\u9898\u2192\u9898\u5e72\u5173\u952e\u8bcd\u2192\u539f\u6587\u5b9a\u4f4d\u2192\u540c\u4e49\u66ff\u6362; "
            "\u63a8\u7406\u9898\u2192\u539f\u6587\u4e8b\u5b9e\u2192\u5408\u7406\u63a8\u65ad(\u4e0d\u80fd\u662f\u539f\u6587\u672a\u63d0\u53ca\u7684); "
            "\u4e3b\u65e8\u9898\u2192\u9996\u6bb5+\u5c3e\u6bb5+\u5404\u6bb5\u9996\u53e5\u2192\u9ad8\u9891\u8bcd; "
            "\u8bcd\u4e49\u731c\u6d4b\u9898\u2192\u524d\u540e\u53e5\u903b\u8f91(\u8f6c\u6298/\u56e0\u679c/\u5e76\u5217)\u2192\u731c\u8bcd\u4e49.\n\n"
            "4. 解析 (Analysis): Explain how the correct option maps to the passage — "
            "\u540c\u4e49\u66ff\u6362, \u76f4\u63a5\u5bf9\u5e94, or \u5408\u7406\u63a8\u65ad.\n\n"
            "5. 排除法 (Elimination): For each wrong option, "
            "'\u274c \u4e0d\u9009 X: reason (\u65e0\u4e2d\u751f\u6709/\u5077\u6362\u6982\u5ff5/\u4e0e\u539f\u6587\u76f8\u53cd)'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "number": {"type": "integer"},
                            "answer": {"type": "string", "enum": ["A", "B", "C", "D"]},
                            "modules": {
                                "type": "object",
                                "properties": {
                                    "\u9898\u5e72\u5b9a\u4f4d": {"type": "string"},
                                    "\u9009\u9879\u8bcd\u4e49": {"type": "string"},
                                    "\u8003\u70b9": {"type": "string"},
                                    "\u89e3\u6790": {"type": "string"},
                                    "\u6392\u9664\u6cd5": {"type": "string"},
                                },
                                "required": [
                                    "\u9898\u5e72\u5b9a\u4f4d", "\u9009\u9879\u8bcd\u4e49",
                                    "\u8003\u70b9", "\u89e3\u6790", "\u6392\u9664\u6cd5",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["number", "answer", "modules"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# Stage 2: Generate True/False
# ═══════════════════════════════════════════════════════════════

GENERATE_TRUE_FALSE_DEF = {
    "type": "function",
    "function": {
        "name": "generate_true_false",
        "strict": True,
        "description": (
            "Generate tutorial for true/false/not given exam. For each question, produce exactly 4 modules:\n\n"
            "1. 原句/题干 (Statement with Answer): The statement with answer embedded as "
            "'<u>True</u>', '<u>False</u>', or '<u>Not Given</u>'.\n\n"
            "2. 原文依据 (Passage Evidence): Quote the relevant sentence from the passage with "
            "<u>underline</u>. Format: '\u539f\u6587\u7b2cX\u6bb5\uff1a\"...<u>evidence</u>...\"'. "
            "If no evidence exists, write '\u539f\u6587\u672a\u63d0\u53ca'.\n\n"
            "3. 考点 (Key Point): Identify the trap type: "
            "\u5077\u6362\u4e3b\u8bed/\u5077\u6362\u6570\u5b57/\u5077\u6362\u65f6\u6001/\u65e0\u4e2d\u751f\u6709/\u8fc7\u5ea6\u63a8\u65ad.\n\n"
            "4. 解析 (Analysis): For True: explain how the statement matches the passage. "
            "For False: point out the specific contradiction. "
            "For Not Given: explain why it's neither confirmed nor inferable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "number": {"type": "integer"},
                            "answer": {
                                "type": "string",
                                "enum": ["True", "False", "Not Given"],
                            },
                            "modules": {
                                "type": "object",
                                "properties": {
                                    "\u539f\u53e5/\u9898\u5e72": {"type": "string"},
                                    "\u539f\u6587\u4f9d\u636e": {"type": "string"},
                                    "\u8003\u70b9": {"type": "string"},
                                    "\u89e3\u6790": {"type": "string"},
                                },
                                "required": [
                                    "\u539f\u53e5/\u9898\u5e72", "\u539f\u6587\u4f9d\u636e",
                                    "\u8003\u70b9", "\u89e3\u6790",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["number", "answer", "modules"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
}

# ═══════════════════════════════════════════════════════════════
# Routing tables
# ═══════════════════════════════════════════════════════════════

STAGE1_TOOLS = [PARSE_EXAM_DEF]

STAGE2_TOOL_DEFS = {
    "generate_grammar_cloze": GENERATE_GRAMMAR_CLOZE_DEF,
    "generate_cloze": GENERATE_CLOZE_DEF,
    "generate_open_cloze":   GENERATE_OPEN_CLOZE_DEF,
    "generate_reading_comp": GENERATE_READING_COMP_DEF,
    "generate_true_false":   GENERATE_TRUE_FALSE_DEF,
}

STAGE2_TOOL_NAME = {
    "grammar_cloze": "generate_grammar_cloze",
    "cloze": "generate_cloze",
    "reading_comp": "generate_reading_comp",
    "true_false": "generate_true_false",
}

# (exam_type, variant) → tool_name — used when variant != "multiple_choice"
VARIANT_TOOL_NAME = {
    ("grammar_cloze", "open_ended"): "generate_open_cloze",
    ("cloze", "open_ended"): "generate_open_cloze",
}


def get_tool_definition(name: str) -> dict:
    """Return a single tool definition by name."""
    return STAGE2_TOOL_DEFS[name]


def strip_strict(tool_def):
    """Return a copy of tool_def with 'strict' field removed (for non-strict fallback)."""
    import copy
    d = copy.deepcopy(tool_def)
    if isinstance(d, list):
        for t in d:
            t["function"].pop("strict", None)
    else:
        d["function"].pop("strict", None)
    return d


# ═══════════════════════════════════════════════════════════════
# format_questions_block — for Stage 2 User Prompt
# ═══════════════════════════════════════════════════════════════

def format_questions_block(exam_type: str, questions: list,
                          variant: str = "multiple_choice") -> str:
    """Format question data into a text block for the Stage 2 User Prompt."""
    if variant == "open_ended":
        return "\n\n".join(
            f"Q{q['id']}: {q['context_before']} → [{q['sentence_with_blank']}] → {q['context_after']}"
            for q in questions
        )
    if exam_type in ("grammar_cloze", "cloze"):
        return "\n\n".join(
            f"Q{q['id']}: {q['context_before']} → [{q['sentence_with_blank']}] → {q['context_after']}\n"
            f"   Options: {' | '.join(f'{k}. {v}' for k, v in sorted(q['options'].items()))}"
            for q in questions
        )
    elif exam_type == "reading_comp":
        return "\n\n".join(
            f"Q{q['id']}: {q['stem']}\n"
            f"   Options: {' | '.join(f'{k}. {v}' for k, v in sorted(q['options'].items()))}"
            for q in questions
        )
    elif exam_type == "true_false":
        return "\n".join(f"Q{q['id']}: {q['statement']}" for q in questions)
    return ""
