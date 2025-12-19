# chat_logic.py
"""
Chat logic for NED (route-scoped chat).

Goal:
- Keep Flask routes thin (request/session/redirect).
- Keep business logic here (add/delete/filter/overlap helpers).
- Storage stays in the same JSON structure; route objects carry `chat` list.

Message schema (stored under route["chat"]):
{
  "id": int,
  "author": str,
  "author_id": int | str,
  "text": str,
  "ts": "YYYY-MM-DD HH:MM"
}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re


# ---------------------------
# Basic helpers
# ---------------------------

def now_ts() -> str:
    """Return timestamp in the same format you already use in JSON."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def clean_text(text: str) -> str:
    """Normalize user input for chat messages."""
    return (text or "").strip()


def can_user_post(user: Optional[Dict[str, Any]]) -> bool:
    """
    True if user exists and is allowed to post.
    Convention: user["can_post"] defaults to True.
    """
    if not user:
        return False
    return bool(user.get("can_post", True))


# ---------------------------
# Route chat CRUD
# ---------------------------

def get_route_chat(route: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return chat list for a route (never None)."""
    chat = route.get("chat")
    if isinstance(chat, list):
        return chat
    return []


def next_message_id(chat: List[Dict[str, Any]]) -> int:
    """Compute next incremental message id for a route chat."""
    if not chat:
        return 1
    last = chat[-1]
    last_id = last.get("id")
    return (last_id + 1) if isinstance(last_id, int) else (len(chat) + 1)


def add_route_message(
    route: Dict[str, Any],
    *,
    author: str,
    author_id: Any,
    text: str,
    ts: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Append a message to route["chat"].

    Returns: (ok, error_message)
    """
    msg_text = clean_text(text)
    if not msg_text:
        return False, "Empty message."

    chat = get_route_chat(route)
    msg_id = next_message_id(chat)

    chat.append({
        "id": msg_id,
        "author": author or "user",
        "author_id": author_id,
        "text": msg_text,
        "ts": ts or now_ts(),
    })

    route["chat"] = chat
    return True, None


def delete_route_message(route: Dict[str, Any], msg_id: int) -> bool:
    """
    Hard-delete a message from route["chat"] by id.
    Returns True if a message was removed, False if not found.
    """
    chat = get_route_chat(route)
    before = len(chat)
    chat = [m for m in chat if m.get("id") != msg_id]
    route["chat"] = chat
    return len(chat) != before


# ---------------------------
# Overlap logic (for your "A" approach)
# show "related routes" that share elements
# ---------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def route_tokens(route: Dict[str, Any]) -> set[str]:
    """
    Build a simple token set for overlap detection.
    MVP tokens:
      - departure
      - destination
      - chunks from waypoints_raw/waypoints
    """
    tokens: set[str] = set()

    dep = _norm(route.get("departure", ""))
    dst = _norm(route.get("destination", ""))
    if dep:
        tokens.add(dep)
    if dst:
        tokens.add(dst)

    wp = _norm(route.get("waypoints_raw") or route.get("waypoints") or "")
    for part in re.split(r"[;,\n\-–→]+", wp):
        part = _norm(part)
        if part and len(part) >= 3:
            tokens.add(part)

    return tokens


def routes_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True if two routes share at least one token."""
    return len(route_tokens(a) & route_tokens(b)) > 0


def related_routes_for(
    routes: List[Dict[str, Any]],
    current_route: Dict[str, Any],
    *,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Return a list of routes that overlap with current_route,
    excluding itself, capped to `limit`.
    """
    cur_id = current_route.get("id")
    rel = [r for r in routes if r.get("id") != cur_id and routes_overlap(current_route, r)]
    return rel[:max(0, int(limit))]
