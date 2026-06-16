from django.urls import path
from . import views

urlpatterns = [

    # Dashboard
    path('dashboard/personaldata/', views.get_dashboard_data, name='dashboard_data'),
    path('dashboard/rankings/', views.get_rankings, name='rankings'),

    # Admin
    path('admin/<int:user_id>/', views.get_user_by_id, name='get_user_by_id'),
    path('admin/<int:user_id>/profile/', views.get_user_profile, name='get_user_profile'),
    path('admin/<int:user_id>/update/', views.update_user, name='update_user'),
    path('admin/stats/', views.get_users_with_stats, name='get_users_with_stats'),
    path('admin/<int:user_id>/delete/', views.delete_user, name='delete_user'),    
]