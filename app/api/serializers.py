from __future__ import annotations

import json
from typing import Any


def serialize_poll(row: dict[str, Any]) -> dict[str, Any]:
    poll = dict(row)
    try:
        poll["options"] = json.loads(poll.pop("options_json"))
    except (KeyError, TypeError, json.JSONDecodeError):
        poll["options"] = []
    return poll


def serialize_tenant(row: dict[str, Any]) -> dict[str, Any]:
    tenant = dict(row)
    tenant.pop("password", None)
    return tenant
