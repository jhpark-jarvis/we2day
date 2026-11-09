"""Keep generated date labels consistent without renaming user-supplied titles."""

import re
from datetime import date

from we2day_api.ai_place_policy import norm

FULL_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}|20\d{2}년\s*\d{1,2}월\s*\d{1,2}일")


def generated_title(title, day, user_text, *, existing=False):
    if existing or norm(title) in norm(user_text):
        return title
    target = date.fromisoformat(day)
    supplied_dates = set()
    for match in FULL_DATE.finditer(user_text):
        try:
            supplied_dates.add(date(*[int(n) for n in re.findall(r"\d+", match[0])]))
        except ValueError:
            continue

    def replace(match):
        value = match[0]
        numbers = [int(n) for n in re.findall(r"\d+", value)]
        try:
            observed = date(*numbers)
        except ValueError:
            return value
        if observed == target or observed in supplied_dates:
            return value
        return day if "-" in value else f"{target.year}년 {target.month}월 {target.day}일"

    return FULL_DATE.sub(replace, title)[:100]
