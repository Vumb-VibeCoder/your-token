#!/usr/bin/env python3
"""Ước lượng số token từ văn bản/file. Chỉ là xấp xỉ (không phải tokenizer thật)."""
import argparse, json, math, re, sys
from pathlib import Path

PLANS = Path(__file__).resolve().parent.parent / "plans.json"
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs",
            ".rb", ".php", ".sh", ".json", ".yml", ".yaml", ".html", ".css", ".sql", ".toml"}
VI_CHARS = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")


def cpt_table():
    return json.loads(PLANS.read_text(encoding="utf-8"))["chars_per_token"]


def detect_lang(text, filename=None):
    if filename and Path(filename).suffix.lower() in CODE_EXT:
        return "code"
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return "mixed"
    vi = sum(1 for c in letters if c in VI_CHARS) / len(letters)
    if vi > 0.06:
        return "vi"
    if re.search(r"[{};=()]{3,}|def |function |import ", text):
        return "code"
    return "en"


def est_tokens(text, lang=None, filename=None):
    lang = lang or detect_lang(text, filename)
    return math.ceil(len(text) / cpt_table().get(lang, 3.5))


def chars_to_tokens(chars, lang="mixed"):
    return math.ceil(chars / cpt_table().get(lang, 3.5))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--text")
    ap.add_argument("--lang", choices=["vi", "en", "code", "mixed"])
    a = ap.parse_args()
    if a.file:
        t = Path(a.file).read_text(encoding="utf-8", errors="ignore")
        name = a.file
    else:
        t, name = (a.text or sys.stdin.read()), None
    lang = a.lang or detect_lang(t, name)
    print(f"lang={lang} chars={len(t)} tokens~{est_tokens(t, lang)}")
