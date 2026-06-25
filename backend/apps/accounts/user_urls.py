from django.urls import path
from . import views

urlpatterns = [

    # Dashboard
    path('dashboard/personaldata/', views.get_dashboard_data, name='dashboard_data'),
    path('dashboard/rankings/', views.get_rankings, name='rankings'),

    # Profile    
    path('current-user', views.get_current_user, name='current_user'),   
    path('update-user-profile', views.update_profile, name='update_user_profile'),
    path('update-email-password', views.update_email_password, name='update_email_password'),
    path('update-guest-profile', views.update_guest_profile, name='update_guest_profile'),
    path('deactivate-account', views.deactivate_account, name='deactivate_account'),

    # Admin
    path('<int:user_id>/', views.get_user_by_id, name='get_user_by_id'),
    path('<int:user_id>/profile/', views.get_user_profile, name='get_user_profile'),
    path('stats/', views.get_users_with_stats, name='get_users_with_stats'),
    path('<int:user_id>/delete/', views.delete_user, name='delete_user'),    
]