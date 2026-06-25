# shared/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Endpoints de temas
    path('topics/', views.get_topics_view, name='get_topics'),
    path('topics/main/', views.get_main_topics_view, name='get_main_topics'),
    path('topics/<str:main_topic>/sub_topics/', views.get_sub_topics_view, name='get_sub_topics'),
    path('topics/<str:main_topic>/<str:sub_topic>/specific_topics/', views.get_specific_topics_view, name='get_specific_topics'),
    path('topics/hierarchy/', views.get_topic_hierarchy_view, name='get_topic_hierarchy'),
    path('topics/validate/', views.validate_topic, name='validate_topic'),
    path('topics/statistics/', views.get_topic_statistics_view, name='topic_statistics'),
    
    # Endpoints de administración
    path('topics/create/', views.create_topic, name='create_topic'),
    path('topics/refresh-cache/', views.refresh_cache, name='refresh_cache'),

    # Endpoints de Configuración del Sistema para Usuarios
    path('system-configsForUser/key/<str:key>/', views.get_system_config_by_key, name='get_system_config_by_key'),

]