# results/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Usuarios o compartido
    path('tests/<int:test_id>/save/', views.save_or_update_result, name='save_result'),
    path('tests/<int:test_id>/progress/', views.get_test_progress, name='get_test_progress'),
    path('tests/<int:test_id>/progress/delete/', views.delete_test_progress, name='delete_test_progress'),
    path('tests/in-progress/', views.get_my_in_progress_tests, name='in_progress_tests'),
    path('tests/completed/', views.get_my_completed_tests, name='completed_tests'),
    path('<int:result_id>/incorrect-answers/', views.get_incorrect_answers, name='incorrect_answers'),

    # Admin
    path('', views.get_results_list, name='get_results_list'),
    path('user/<int:user_id>/', views.get_user_results, name='admin_user_results'),
    path('<int:result_id>/user/<int:user_id>/', views.get_user_result_details, name='admin_user_result_details'),
    path('<int:result_id>/delete/', views.delete_result, name='delete_result'),
    path('bulk-delete/', views.delete_results_bulk, name='delete_results_bulk'),
    path('stats/', views.get_result_stats, name='get_result_stats'),
    path('<int:result_id>/', views.get_result_detail, name='get_result_detail'),
    path('export/csv/', views.export_results_csv, name='export_results_csv'),
]