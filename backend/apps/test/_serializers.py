# apps/tests/serializers.py
from rest_framework import serializers # type: ignore
from .models import Test, Question, Answer

class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = ['id', 'answer_text']

class QuestionSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True, read_only=True)
    
    class Meta:
        model = Question
        fields = ['id', 'question_text', 'answers']

class TestSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    total_questions = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Test
        fields = '__all__'

class CreateTestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    main_topic = serializers.CharField(max_length=255)
    sub_topic = serializers.CharField(max_length=255)
    specific_topic = serializers.CharField(max_length=255)
    level = serializers.ChoiceField(choices=['Principiante', 'Intermedio', 'Avanzado'])
    is_active = serializers.BooleanField(default=True)
    questions = serializers.ListField(child=serializers.DictField())