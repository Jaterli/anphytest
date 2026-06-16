# admin_panel/models.py
from django.db import models


class UserQuota(models.Model):
    """Modelo para gestionar cuotas de usuarios"""
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='quotas'
    )
    month_year = models.CharField(max_length=7, db_index=True)  # Formato: YYYY-MM
    max_requests = models.IntegerField(default=5)
    used_requests = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_quotas'
        unique_together = ['user', 'month_year']
        indexes = [
            models.Index(fields=['user_id', 'month_year']),
            models.Index(fields=['month_year']),
            models.Index(fields=['max_requests']),
            models.Index(fields=['used_requests']),
        ]
        ordering = ['-month_year']

    def __str__(self):
        return f"Quota for {self.user.username} - {self.month_year}"

    @property
    def remaining_requests(self):
        return max(0, self.max_requests - self.used_requests)

    @property
    def usage_percentage(self):
        if self.max_requests > 0:
            return min(100, int((self.used_requests * 100) / self.max_requests))
        return 0

    @property
    def status(self):
        percentage = self.usage_percentage
        if self.used_requests >= self.max_requests:
            return 'exceeded'
        elif percentage >= 80:
            return 'critical'
        elif percentage >= 50:
            return 'warning'
        return 'normal'


class SystemConfig(models.Model):
    """Modelo para almacenar configuraciones del sistema"""
    key = models.CharField(max_length=255, unique=True, db_index=True)
    value = models.TextField()
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'system_configs'
        ordering = ['key']
        indexes = [
            models.Index(fields=['key']),
        ]

    def __str__(self):
        return f"{self.key} = {self.value[:50]}"