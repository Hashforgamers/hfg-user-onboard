from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from db.extensions import db


class NotificationDispatchJob(db.Model):
    __tablename__ = "notification_dispatch_jobs"

    id = Column(Integer, primary_key=True)
    status = Column(String(20), nullable=False, index=True, default="queued")  # queued|running|completed|failed
    force = Column(Boolean, nullable=False, default=False)
    dry_run = Column(Boolean, nullable=False, default=False)
    retry_failed = Column(Boolean, nullable=False, default=False)

    notification_title = Column(String(160), nullable=True)
    notification_message = Column(Text, nullable=True)

    tokens_found = Column(Integer, nullable=False, default=0)
    tokens_blocked = Column(Integer, nullable=False, default=0)
    tokens_attempted = Column(Integer, nullable=False, default=0)
    sent = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)

    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "force": self.force,
            "dry_run": self.dry_run,
            "retry_failed": self.retry_failed,
            "notification": {
                "title": self.notification_title,
                "message": self.notification_message,
            },
            "tokens_found": self.tokens_found,
            "tokens_blocked": self.tokens_blocked,
            "tokens_attempted": self.tokens_attempted,
            "sent": self.sent,
            "failed": self.failed,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class NotificationDispatchFailure(db.Model):
    __tablename__ = "notification_dispatch_failures"

    id = Column(Integer, primary_key=True)
    token = Column(String(512), nullable=False, unique=True, index=True)
    error_type = Column(String(120), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    failure_count = Column(Integer, nullable=False, default=1)
    is_blocked = Column(Boolean, nullable=False, default=True, index=True)
    first_failed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_failed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    last_job_id = Column(Integer, nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "token_prefix": (self.token[:12] + "...") if self.token else None,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "failure_count": self.failure_count,
            "is_blocked": self.is_blocked,
            "first_failed_at": self.first_failed_at.isoformat() if self.first_failed_at else None,
            "last_failed_at": self.last_failed_at.isoformat() if self.last_failed_at else None,
            "last_job_id": self.last_job_id,
        }
