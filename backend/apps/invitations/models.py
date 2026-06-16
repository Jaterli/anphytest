# apps/invitations/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import secrets
import logging

logger = logging.getLogger(__name__)


class TestInvitation(models.Model):
    """Modelo para invitaciones a tests"""
    test = models.ForeignKey(
        'test.Test',
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_invitations'
    )
    guest_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_invitations'
    )
    message = models.TextField(blank=True, default='')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    is_used = models.BooleanField(default=False, db_index=True)
    is_guest = models.BooleanField(default=False, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'test_invitations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['test', 'is_used']),
            models.Index(fields=['invited_by', 'created_at']),
            models.Index(fields=['guest_user', 'is_used']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"Invitation to {self.test.title} by {self.invited_by.username}"

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(32)
        if not self.expires_at:
            # FIX: timezone.timedelta does not exist; use datetime.timedelta
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def status(self):
        if self.is_used:
            return 'used'
        if self.expires_at < timezone.now():
            return 'expired'
        return 'active'

    @property
    def is_expired(self):
        return self.expires_at < timezone.now()

    @property
    def invitation_url(self):
        base_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
        return f"{base_url}/invitation/accept?token={self.token}"


class InvitationEvent(models.Model):
    """Modelo para registrar eventos de invitaciones (auditoría)"""
    EVENT_TYPES = [
        ('created', 'Created'),
        ('viewed', 'Viewed'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('deleted', 'Deleted'),
        ('transferred', 'Transferred'),
    ]

    invitation = models.ForeignKey(
        TestInvitation,
        on_delete=models.CASCADE,
        related_name='events'
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='invitation_events'
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'invitation_events'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.event_type} - {self.invitation.token} at {self.created_at}"