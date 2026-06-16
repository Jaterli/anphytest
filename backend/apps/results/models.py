# results/models.py
from django.db import models
from django.utils import timezone

class Result(models.Model):
    STATUS_CHOICES = (
        ('in_progress', 'En progreso'),
        ('completed', 'Completado'),
        ('abandoned', 'Abandonado'),
    )

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='results')
    test = models.ForeignKey('test.Test', on_delete=models.CASCADE, related_name='results')
    correct_answers = models.IntegerField(default=0)
    wrong_answers = models.IntegerField(default=0)
    time_taken = models.IntegerField(default=0)  # segundos
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    answers = models.JSONField(default=dict)  # {question_id: answer_id}
    started_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'results'
        indexes = [
            models.Index(fields=['user', 'test', 'status']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['test', 'status']),
        ]

    @property
    def total_answered(self):
        return len(self.answers) if self.answers else 0

    @property
    def score_percentage(self):
        total = self.correct_answers + self.wrong_answers
        if total == 0:
            return 0
        return round(self.correct_answers / total * 100, 2)