import enum


class ContactSource(str, enum.Enum):
    chat = "chat"
    voice = "voice"
    staff = "staff"


class Gender(str, enum.Enum):
    # Only ever set from something the person stated. Never inferred from a
    # name: a wrong guess misaddresses a real customer; NULL costs nothing.
    male = "male"
    female = "female"


class Team(str, enum.Enum):
    sales = "sales"
    ops = "ops"
    support = "support"
    privacy = "privacy"


class Channel(str, enum.Enum):
    chat = "chat"
    voice = "voice"


class IdentityKind(str, enum.Enum):
    anonymous = "anonymous"
    customer = "customer"
    staff = "staff"


class TicketPriority(str, enum.Enum):
    normal = "normal"
    urgent = "urgent"
    privacy = "privacy"


class TicketReason(str, enum.Enum):
    discount = "discount"
    premium_quote = "premium_quote"
    long_event = "long_event"
    late_change = "late_change"
    complaint = "complaint"
    live_issue = "live_issue"
    legal = "legal"
    unknown_question = "unknown_question"
    wants_human = "wants_human"


class TicketStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class BookingStatus(str, enum.Enum):
    # No `draft`: a draft lives only inside a confirmation token (spec §8).
    tentative = "tentative"
    confirmed = "confirmed"
    live = "live"
    ended = "ended"
    cancelled = "cancelled"


class MatchMode(str, enum.Enum):
    # Same values as Laqta's MatchMode (api/app/models/enums.py).
    face = "face"
    code = "code"
    sequential = "sequential"
    both = "both"


class ConfirmationAction(str, enum.Enum):
    booking = "booking"
    reschedule = "reschedule"
    cancel = "cancel"


class KBAudience(str, enum.Enum):
    public = "public"
    internal = "internal"
