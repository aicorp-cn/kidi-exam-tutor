"""Pinyin — surname initial extraction using pypinyin."""
from pypinyin import lazy_pinyin


def surname_initial(name: str) -> str:
    """Return uppercase first letter of surname pinyin. e.g. '张三' → 'Z'."""
    if not name:
        return "X"
    first_char = name[0]
    try:
        py = lazy_pinyin(first_char)
        return py[0][0].upper() if py and py[0] else "X"
    except Exception:
        return "X"
