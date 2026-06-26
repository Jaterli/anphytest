# admin_panel/urls.py
from django.urls import path
from . import views

urlpatterns = [

    # Endpoints de Cuotas de Usuario
    path('quotas/', views.admin_get_user_quotas, name='admin_get_user_quotas'),
    path('quotas/stats/', views.admin_get_quota_stats, name='admin_quota_stats'),
    path('quotas/create/', views.admin_create_user_quota, name='admin_create_quota'),
    path('quotas/bulk-delete/', views.admin_delete_quotas_bulk, name='admin_delete_quotas_bulk'),
    path('quotas/export/csv/', views.admin_export_quotas_csv, name='admin_export_quotas_csv'),
    path('quotas/<int:quota_id>/update/', views.admin_update_user_quota, name='admin_update_quota'),
    path('quotas/<int:quota_id>/delete/', views.admin_delete_user_quota, name='admin_delete_quota'),
    path('users/<int:user_id>/quotas/', views.admin_get_user_quota, name='admin_get_user_quota'),
    path('users/<int:user_id>/quota-months/', views.admin_get_user_quota_months, name='admin_user_quota_months'),

    # Endpoints de Configuración del Sistema
    path('system-configs/', views.admin_get_system_configs, name='admin_get_system_configs'),
    path('system-configs/grouped/', views.admin_get_system_configs_grouped, name='admin_get_system_configs_grouped'),
    path('system-configs/default/', views.admin_get_default_system_configs, name='admin_get_default_system_configs'),
    path('system-configs/export/csv/', views.admin_export_system_configs_csv, name='admin_export_system_configs_csv'),
    path('system-configs/create/', views.admin_create_system_config, name='admin_create_system_config'),
    path('system-configs/key/<str:key>/', views.admin_get_system_config_by_key, name='admin_get_system_config_by_key'),
    path('system-configs/<int:config_id>/', views.admin_get_system_config, name='admin_get_system_config'),
    path('system-configs/<int:config_id>/update/', views.admin_update_system_config, name='admin_update_system_config'),
    path('system-configs/<int:config_id>/delete/', views.admin_delete_system_config, name='admin_delete_system_config'),

    # Endpoints del Dashboard
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/activity-summary/', views.get_dashboard_activity_summary, name='dashboard_activity_summary'),
    path('dashboard/performance-metrics/', views.get_dashboard_performance_metrics, name='dashboard_performance_metrics'),
    path('dashboard/tests/<int:test_id>/stats/', views.get_test_detailed_stats, name='test_detailed_stats'),
    path('dashboard/users/<int:user_id>/stats/', views.get_user_detailed_stats, name='user_detailed_stats'),
]