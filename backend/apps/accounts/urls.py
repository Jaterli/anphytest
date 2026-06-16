from django.urls import path
from . import views


urlpatterns = [

    path('register', views.register, name='register'),
    path('login', views.login, name='login'),
    path('check-auth', views.check_auth, name='check_auth'),
    path('logout', views.logout, name='logout'),
    path('forgot-password', views.forgot_password, name='forgot_password'),
    path('reset-password', views.reset_password, name='reset_password'),
    path('validate-reset-token', views.validate_reset_token, name='validate_token'),
    path('deactivate-account', views.deactivate_account, name='deactivate_account'),

    # Profile    
    path('current-user', views.get_current_user, name='current_user'),   
    path('update-user-profile', views.update_profile, name='update_user_profile'),
    path('update-email-password', views.update_email_password, name='update_email_password'),
    path('update-guest-profile', views.update_guest_profile, name='update_guest_profile'),

]
