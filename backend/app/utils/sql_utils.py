# app/utils/sql_utils.py
"""Helpers for building parameterised asyncpg SQL ($1, $2, ...)."""

from typing import Any, List


class Params:
    """Collects query parameters and hands back their placeholders.

        p = Params()
        where = [f"d.code = {p.add(code)}"]
        rows = await db_manager.execute_query(sql, p.values, fetch_all=True)
    """

    def __init__(self, *initial: Any) -> None:
        self.values: List[Any] = list(initial)

    def add(self, value: Any) -> str:
        self.values.append(value)
        return f"${len(self.values)}"


def like_pattern(word: str) -> str:
    """'%word%' with LIKE wildcards escaped; pair with ESCAPE '\\' in the SQL."""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
