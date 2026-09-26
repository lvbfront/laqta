"""One error shape, and the Arabic the widget shows for it.

The widget renders `message_ar` and nothing else, so every code here needs
one. `retryable` is the widget's instruction, not a description: false means
this conversation is over and it should offer a new one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatError(Exception):
    code: str
    message_ar: str
    status: int
    retryable: bool = True

    def body(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message_ar": self.message_ar,
                "retryable": self.retryable,
            }
        }


def session_not_found() -> ChatError:
    return ChatError(
        "session_not_found",
        "انتهت هذي المحادثة. نبدأ وحدة جديدة؟",
        404,
        retryable=False,
    )


def session_ended() -> ChatError:
    return ChatError("session_ended", "هذي المحادثة خلصت. نبدأ وحدة جديدة؟", 409, retryable=False)


def session_broken() -> ChatError:
    """Something failed in a way that leaves the session's state untrustworthy
    — a turn that raised, or a confirmation token that could not be voided.
    Refusing the whole conversation is the only honest answer: the customer
    starts again, and nothing they say lands against state we cannot vouch
    for."""
    return ChatError(
        "session_broken",
        "صار خلل ما نقدر نكمل بعده. نبدأ محادثة جديدة؟",
        409,
        retryable=False,
    )


def model_unavailable() -> ChatError:
    return ChatError("model_unavailable", "صار عندي خلل تقني بسيط. جرب مرة ثانية.", 503)


def message_too_long(limit: int) -> ChatError:
    return ChatError("message_too_long", f"الرسالة طويلة. الحد {limit} حرف.", 422)


def empty_message() -> ChatError:
    return ChatError("empty_message", "اكتب رسالتك أول.", 422)


def too_many_sessions() -> ChatError:
    return ChatError("too_many_sessions", "الخدمة مشغولة حالياً. جرب بعد شوي.", 503)


def bad_identity(detail: str) -> ChatError:
    return ChatError("bad_identity", f"هوية غير صالحة: {detail}", 400, retryable=False)


def bad_now(detail: str) -> ChatError:
    return ChatError("bad_now", f"تاريخ غير صالح: {detail}", 400, retryable=False)
