# norm.py
import json
import os
import re

ALIASES_FILE = os.path.join(os.path.dirname(__file__), "alltickers.json")


with open(ALIASES_FILE, "r", encoding="utf-8") as f:
    nested = json.load(f)

alias_dict = {}
for category, mapping in nested.items():
    for key, ticker in mapping.items():
        alias_dict[key.lower()] = ticker

_clean_re = re.compile(r"[^a-z0-9]")

def normalize_symbol(user_input: str) -> str:
    clean = _clean_re.sub("", user_input.lower())
    return alias_dict.get(clean, user_input.upper())