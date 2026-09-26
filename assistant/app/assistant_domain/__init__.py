"""Pure, clock-free logic that is the assistant's own.

Same discipline as app/domain/ — no LLM calls, no clock, `now` always passed
in — but none of it belongs to the Laqta platform. A dashboard has a date
picker and a confirm button; it needs neither natural-language date
resolution nor a token proving a customer was given a chance to reply.

Kept apart from app/domain/ so that folder stays a straight lift into the
Laqta API. See docs/ARCHITECTURE.md.
"""
