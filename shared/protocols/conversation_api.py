"""Core's conversation routes. Hub to core only; every call carries the service token."""

CONVERSATION = "/conversation"
CONVERSATION_FORGET = "/conversation/forget"  # POST {session_id, history_scope}: drop the short-term history held for one saved chat
