# apps/invitations/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Endpoints públicos (shared)
    path('create/', views.create_invitation, name='create_invitation'),
    path('check-invitation/', views.check_invitation, name='check_invitation'),
    path('accept-invitation/', views.accept_invitation, name='accept_invitation'),
    path('my-invitations/', views.get_user_invitations, name='user_invitations'),

    # Endpoints para el Admin
    path('admin/list/', views.admin_get_invitations, name='admin_invitations'),
    path('admin/stats/', views.admin_get_invitation_stats, name='admin_invitation_stats'),
    path('admin/<int:invitation_id>/', views.admin_get_invitation_detail, name='admin_invitation_detail'),
    path('admin/<int:invitation_id>/delete/', views.admin_delete_invitation, name='admin_delete_invitation'),
    path('admin/bulk-delete/', views.admin_delete_invitations_bulk, name='admin_delete_invitations_bulk'),
]