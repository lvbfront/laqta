"""Import every model so app.db.Base.metadata is fully populated —
required for Alembic autogenerate and for create_all() in tests.
"""

from app.models.audit_log import AuditLog
from app.models.download import Download
from app.models.event import Event
from app.models.event_ftp_credential import EventFtpCredential
from app.models.face import Face
from app.models.guest import Guest
from app.models.guest_face import GuestFace
from app.models.match import Match
from app.models.organization import Organization
from app.models.photo import Photo
from app.models.photo_code import PhotoCode
from app.models.photographer import Photographer
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "AuditLog",
    "Download",
    "Event",
    "EventFtpCredential",
    "Face",
    "Guest",
    "GuestFace",
    "Match",
    "Organization",
    "Photo",
    "PhotoCode",
    "Photographer",
    "User",
    "UserSession",
]
