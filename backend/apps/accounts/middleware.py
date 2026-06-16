# apps/accounts/middleware.py
from django.utils.deprecation import MiddlewareMixin
from .models import User

class JWTCookieMiddleware:
    """Middleware para autenticación JWT vía cookie o header"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Establecer user por defecto como None
        request.user = None
        
        # Intentar obtener token
        auth_header = request.headers.get('Authorization', '')
        token = None
        
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        else:
            token = request.COOKIES.get('auth_token')
        
        if token:
            # Importación diferida para evitar circular imports
            from .views import get_user_from_token
            user = get_user_from_token(token)
            if user and user.is_active:
                request.user = user
        
        return self.get_response(request)