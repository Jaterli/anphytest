# ai/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('generate-ai-test/', views.generate_ai_test, name='generate_ai_test'),
    path('quota/', views.get_current_user_quota, name='ai_quota'),

    # Logs de solicitudes
    path('logs/', views.get_ai_request_logs, name='ai_logs'),
    path('logs/<int:log_id>/', views.get_ai_request_detail, name='ai_log_detail'),
]