import uuid

from sqlalchemy import BigInteger, Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from db.extensions import db


class UserDeletionArchive(db.Model):
    __tablename__ = "user_deletion_archives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_user_id = Column(BigInteger, nullable=False, index=True)
    original_fid_hash = Column(String(64), nullable=True)
    deletion_status = Column(String(32), nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    purged_at = Column(DateTime(timezone=True), nullable=True)
    record_manifest = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
