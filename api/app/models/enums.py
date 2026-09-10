import enum


class AccountType(str, enum.Enum):
    organizer = "organizer"
    photographer = "photographer"


class UserRole(str, enum.Enum):
    owner = "owner"
    staff = "staff"
    photographer = "photographer"
    moderator = "moderator"


class EventStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    closed = "closed"


class PrivacyMode(str, enum.Enum):
    standard = "standard"
    strict = "strict"


class MatchMode(str, enum.Enum):
    face = "face"
    code = "code"
    both = "both"
    # A photo booth, not a moderation queue: a staff member taps "next
    # guest" (Event.current_solo_number advances) between subjects, and
    # every photo that lands while a number is "open" is auto-tagged with
    # it (app/services/ingest.py) -- no biometric data, no staff typing a
    # code by hand afterward. Same guest-facing lookup as 'code'
    # (app/api/routes/match.py's match_by_code), just a different way of
    # getting the PhotoCode row created.
    sequential = "sequential"


class PhotoStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class MatchFeedback(str, enum.Enum):
    not_me = "not_me"
    remove_requested = "remove_requested"
