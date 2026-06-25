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
]
