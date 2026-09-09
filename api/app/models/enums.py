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


class PhotoStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class MatchFeedback(str, enum.Enum):
    not_me = "not_me"
    remove_requested = "remove_requested"
