"""Version ownership shared by normal turns, server answers and side questions."""

import copy


def current_context(value, version):
    result = copy.deepcopy(value)
    dialogue = result.get("dialogue") or {}
    if dialogue.get("turn_version", 0) != version:
        dialogue.update(pending=None, append_pending=False)
    result["dialogue"] = dialogue
    for name in ("intake", "activity_edit", "pending_fields"):
        item = result.get(name)
        if item and item.get("turn_version") != version:
            if name == "intake":
                item["pending"] = None
            else:
                result[name] = None
    for name in ("location_request", "schedule_read"):
        item = result.get(name)
        if item and item.get("basis") != version:
            result[name] = None
    return result


def advance_context(value, version):
    """A server-only answer consumes a turn without consuming its open question."""
    # The caller already normalized the loaded context. A handler may have
    # created a valid next-version question/date while producing this answer.
    result = copy.deepcopy(value)
    # Newly-created questions/read dates may already own the next version.
    for name in ("dialogue", "intake", "activity_edit", "pending_fields"):
        item = result.get(name)
        if item and item.get("turn_version", 0) == version:
            item["turn_version"] = version + 1
    for name in ("location_request", "schedule_read", "control"):
        item = result.get(name)
        if item and item.get("basis") == version:
            item["basis"] = version + 1
    return result
