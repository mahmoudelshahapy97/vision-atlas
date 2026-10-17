# app/utils/slug_utils.py
"""URL slugs for catalog entries."""

import re


def slugify(value: str) -> str:
    value = value.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")
