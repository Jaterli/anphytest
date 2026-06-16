# test/models.py
from django.db import models
from typing import TYPE_CHECKING

class Test(models.Model):
    LEVEL_CHOICES = (
        ('Principiante', 'Principiante'),
        ('Intermedio', 'Intermedio'),
        ('Avanzado', 'Avanzado'),
    )
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    main_topic = models.CharField(max_length=255, default='General')
    sub_topic = models.CharField(max_length=255, default='General')
    specific_topic = models.CharField(max_length=255, default='General')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    created_by = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='tests')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    if TYPE_CHECKING:
        questions: models.QuerySet['Question']        

    class Meta:
        db_table = 'tests'
        indexes = [
            models.Index(fields=['main_topic', 'sub_topic']),
            models.Index(fields=['level']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self):
        return self.title
    
    @property
    def total_questions(self):
        return self.questions.count()

    @property
    def questions_prefetched(self):
        """Retorna las preguntas precargadas o las carga si es necesario"""
        if not hasattr(self, '_questions_prefetched'):
            self._questions_prefetched = self.questions.all()
        return self._questions_prefetched
        
    @questions_prefetched.setter
    def questions_prefetched(self, value):
        """Permite asignar preguntas precargadas"""
        self._questions_prefetched = value



class Question(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()

    if TYPE_CHECKING:
        answers: models.QuerySet['Answer']

    class Meta:
        db_table = 'questions'
    
    def __str__(self):
        return self.question_text[:50]


class Answer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    answer_text = models.TextField()
    is_correct = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'answers'
    
    def __str__(self):
        return self.answer_text[:50]