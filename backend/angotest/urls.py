# angotest/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions # type: ignore
from drf_yasg.views import get_schema_view # type: ignore
from drf_yasg import openapi # type: ignore

schema_view = get_schema_view(
    openapi.Info(
        title="AnGoTest API",
        default_version='v1',
        description="API para plataforma de tests online",
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    path('admin/', admin.site.urls),   
    path('api/admin/', include('apps.admin_panel.urls')),   
    path('api/auth/', include('apps.accounts.urls')),
    path('api/user/', include('apps.accounts.user_urls')),
    path('api/test/', include('apps.test.urls')),
    path('api/results/', include('apps.results.urls')),
    path('api/rankings/', include('apps.rankings.urls')),
    path('api/invitations/', include('apps.invitations.urls')),
    path('api/ai/', include('apps.ai.urls')),
    path('api/shared/', include('apps.shared.urls')),

    # Swagger
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
]