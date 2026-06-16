# views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
from datetime import datetime, timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.db import transaction
from django.contrib.auth import logout as django_logout
from functools import wraps
import json
import jwt # type: ignore
import secrets
import logging

from .models import User, PasswordResetToken
from .serializers import UserResponseSerializer
from apps.results.models import Result
from apps.invitations.models import TestInvitation
from django.db.models import Count, Avg, Q, F, FloatField, Case, When, Value, OuterRef, Subquery
from django.db.models.functions import Coalesce, Cast, Round
from .services import DataService, MIN_TESTS_FOR_RANKING, PREDEFINED_LEVELS

logger = logging.getLogger(__name__)


# ============== FUNCIONES AUXILIARES ==============

def user_to_response(user):
    """Convierte un objeto User a diccionario de respuesta (ÚNICA DEFINICIÓN)"""
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'phone': user.phone,
        'address': user.address,
        'country': user.country,
        'birth_date': user.birth_date.isoformat() if user.birth_date else None,
        'role': user.role,
        'registered_at': user.registered_at.isoformat() if user.registered_at else None,
        'login_at': user.login_at.isoformat() if user.login_at else None,
    }


def get_user_from_token(token):
    """Obtiene el usuario a partir del token JWT"""
    try:
        secret = settings.JWT_SECRET
        if not secret:
            return None
        
        payload = jwt.decode(token, secret, algorithms=['HS256'])
        user_id = payload.get('user_id')
        
        if not user_id:
            return None
        
        # Usar solo() para mejorar rendimiento
        return User.objects.only('id', 'email', 'username', 'role', 'is_active').filter(id=user_id).first()
        
    except jwt.InvalidTokenError:
        return None


def generate_jwt_token(user, is_guest=False):
    """Genera un token JWT para el usuario"""
    secret = settings.JWT_SECRET
    if not secret:
        raise ValueError("JWT_SECRET no configurado en el entorno")
    
    payload = {
        'user_id': user.id,
        'role': user.role,
        'is_guest': is_guest,
        'exp': timezone.now() + timedelta(hours=24),
        'iat': timezone.now(),
    }
    
    return jwt.encode(payload, secret, algorithm='HS256')


def get_token_from_request(request):
    """Extrae el token de Authorization header o cookie"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    return request.COOKIES.get('auth_token')


def set_auth_cookie(response, user, is_guest=False):
    """Configura la cookie de autenticación"""
    try:
        token = generate_jwt_token(user, is_guest)
        
        # Actualizar login_at
        user.login_at = timezone.now()
        user.save(update_fields=['login_at'])
        
        # Configuración de la cookie
        is_production = getattr(settings, 'ENV', 'development') == 'production'
        
        response.set_cookie(
            'auth_token',
            token,
            max_age=24 * 60 * 60,
            path='/',
            domain=None,
            secure=is_production,
            httponly=True,
            samesite='Strict' if is_production else 'Lax'
        )
        
        logger.info(f"Setting auth cookie | secure={is_production} | env={settings.ENV}")
        
    except Exception as e:
        logger.error(f"Error setting auth cookie: {str(e)}")
        raise


# ============== DECORADORES ==============

def login_required(view_func):
    """Decorador para verificar autenticación"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Primero verificar si request.user ya está seteado por middleware
        if hasattr(request, 'user') and request.user and request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        
        # Si no, intentar autenticar desde token
        token = get_token_from_request(request)
        if token:
            user = get_user_from_token(token)
            if user and user.is_active:
                request.user = user
                return view_func(request, *args, **kwargs)
        
        return JsonResponse({'error': 'Usuario no autenticado'}, status=401)
    return wrapper


def admin_required(view_func):
    """Decorador para verificar rol de administrador"""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'admin':
            logger.warning(f"Acceso denegado: usuario {request.user.id} con rol {request.user.role} intentó acceder a admin")
            return JsonResponse({'error': 'Acceso denegado. Se requieren privilegios de administrador'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


# ============== AUTENTICACIÓN ==============

@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    """Registro de nuevos usuarios"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    # Validaciones
    required_fields = ['username', 'email', 'password', 'country', 'birth_date']
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return JsonResponse({'error': f'Campos requeridos faltantes: {", ".join(missing_fields)}'}, status=400)
    
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    country = data.get('country', '').strip()
    birth_date_str = data.get('birth_date', '')
    
    # Validaciones
    if len(username) < 3:
        return JsonResponse({'error': 'El username debe tener al menos 3 caracteres'}, status=400)
    if len(password) < 6:
        return JsonResponse({'error': 'La contraseña debe tener al menos 6 caracteres'}, status=400)
    if not country:
        return JsonResponse({'error': 'El país es requerido'}, status=400)
    if '@' not in email or '.' not in email:
        return JsonResponse({'error': 'Formato de email inválido'}, status=400)
    
    # Verificar existencia
    if User.objects.filter(email=email).exists():
        return JsonResponse({'error': 'El email ya está registrado'}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({'error': 'El nombre de usuario ya está en uso'}, status=400)
    
    # Parsear fecha
    try:
        birth_date = datetime.strptime(birth_date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}, status=400)
    
    # Crear usuario
    try:
        user = User(
            username=username,
            email=email,
            password=make_password(password),
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            phone=data.get('phone', ''),
            address=data.get('address', ''),
            country=country,
            birth_date=birth_date,
            role=data.get('role', 'user')
        )
        user.save()
        
        return JsonResponse({'user': UserResponseSerializer(user).data}, status=201)
        
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        return JsonResponse({'error': 'Error al crear usuario'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    """Login de usuarios"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    email = data.get('email', '').lower()
    password = data.get('password', '')
    
    if not email or not password:
        return JsonResponse({'error': 'Email y contraseña son requeridos'}, status=400)
    
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Credenciales inválidas'}, status=401)
    
    if not check_password(password, user.password):
        return JsonResponse({'error': 'Credenciales inválidas'}, status=401)
    
    if not user.is_active:
        return JsonResponse({'error': 'Cuenta desactivada'}, status=401)
    
    # Generar token
    token = generate_jwt_token(user, False)
    
    response = JsonResponse({
        'user': UserResponseSerializer(user).data,
        'message': 'Login exitoso',
        'access_token': token,
        'token_type': 'Bearer'
    })
    
    # Configurar cookie
    try:
        set_auth_cookie(response, user, False)
    except Exception as e:
        logger.error(f"Error setting auth cookie: {str(e)}")
    
    return response


@require_http_methods(["GET"])
def check_auth(request):
    """Verificar autenticación del usuario"""
    token = get_token_from_request(request)
    
    if not token:
        return JsonResponse({'authenticated': False})
    
    user = get_user_from_token(token)
    
    if not user or not user.is_active:
        return JsonResponse({'authenticated': False})
    
    return JsonResponse({
        'authenticated': True,
        'user': UserResponseSerializer(user).data
    })


@csrf_exempt
@require_http_methods(["POST"])
def logout(request):
    """Cierre de sesión"""
    response = JsonResponse({'message': 'Sesión cerrada exitosamente'})
    response.delete_cookie('auth_token', path='/')
    return response


# ============== RECUPERACIÓN DE CONTRASEÑA ==============

def send_password_reset_email(to_email, reset_link):
    """Envía email de recuperación de contraseña"""
    subject = 'Recuperación de contraseña'
    html_message = render_to_string('emails/password_reset.html', {
        'reset_link': reset_link,
        'expires_in': '24 horas'
    })
    plain_message = f"""
    Para restablecer tu contraseña, haz clic en el siguiente enlace:
    {reset_link}
    
    Este enlace expirará en 24 horas.
    
    Si no solicitaste este cambio, ignora este mensaje.
    """
    
    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        html_message=html_message,
        fail_silently=False
    )


@csrf_exempt
@require_http_methods(["POST"])
def forgot_password(request):
    """Solicitar recuperación de contraseña"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    email = data.get('email', '').lower()
    
    if not email:
        return JsonResponse({'error': 'Email es requerido'}, status=400)
    
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # No revelar si el email existe por seguridad
        return JsonResponse({
            'message': 'Si el email existe, se ha enviado un enlace de recuperación'
        })
    
    # Generar token
    token = secrets.token_hex(32)
    
    reset_token = PasswordResetToken(
        user=user,
        token=token,
        used=False,
        expires_at=timezone.now() + timedelta(hours=24)
    )
    reset_token.save()
    
    reset_link = f"https://{request.get_host()}/reset-password?token={token}"
    logger.info(f"Password reset link for {user.email}: {reset_link}")
    
    # Enviar email (en desarrollo, también devolvemos el link)
    try:
        send_password_reset_email(user.email, reset_link)
    except Exception as e:
        logger.error(f"Error sending password reset email: {str(e)}")
    
    response_data = {'message': 'Si el email existe, se ha enviado un enlace de recuperación'}
    
    # Solo en desarrollo devolver el link
    if getattr(settings, 'ENV', 'development') == 'development':
        response_data['reset_link'] = reset_link
    
    return JsonResponse(response_data)


@require_http_methods(["GET"])
def validate_reset_token(request):
    """Validar si un token es válido"""
    token = request.GET.get('token')
    
    if not token:
        return JsonResponse({'error': 'Token requerido'}, status=400)
    
    try:
        token_record = PasswordResetToken.objects.get(
            token=token,
            used=False,
            expires_at__gt=timezone.now()
        )
        return JsonResponse({'valid': True, 'message': 'Token válido'})
    except PasswordResetToken.DoesNotExist:
        return JsonResponse({'valid': False, 'error': 'Token inválido o expirado'}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def reset_password(request):
    """Restablecer contraseña con token"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    token = data.get('token', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')
    
    if not token or not new_password or not confirm_password:
        return JsonResponse({'error': 'Token, nueva contraseña y confirmación son requeridos'}, status=400)
    
    if new_password != confirm_password:
        return JsonResponse({'error': 'Las contraseñas no coinciden'}, status=400)
    
    if len(new_password) < 6:
        return JsonResponse({'error': 'La contraseña debe tener al menos 6 caracteres'}, status=400)
    
    try:
        token_record = PasswordResetToken.objects.select_related('user').get(
            token=token,
            used=False,
            expires_at__gt=timezone.now()
        )
    except PasswordResetToken.DoesNotExist:
        return JsonResponse({'error': 'Token inválido o expirado'}, status=400)
    
    # Actualizar contraseña
    user = token_record.user
    user.password = make_password(new_password)
    user.save(update_fields=['password'])
    
    # Marcar token como usado
    token_record.used = True
    token_record.save(update_fields=['used'])
    
    return JsonResponse({'message': 'Contraseña actualizada exitosamente'})


# ============== PERFIL DE USUARIO ==============

@require_http_methods(["GET"])
@login_required
def get_current_user(request):
    """Obtener usuario actual autenticado"""
    return JsonResponse({
        'user': user_to_response(request.user)
    })


@csrf_exempt
@require_http_methods(["PUT"])
@login_required
def update_profile(request):
    """Actualizar perfil de usuario"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    # Validaciones
    username = data.get('username', '').strip()
    if not username or len(username) < 3 or len(username) > 30:
        return JsonResponse({'error': 'Username debe tener entre 3 y 30 caracteres'}, status=400)
    
    if not data.get('first_name'):
        return JsonResponse({'error': 'Nombre es requerido'}, status=400)
    
    if not data.get('last_name'):
        return JsonResponse({'error': 'Apellido es requerido'}, status=400)
    
    if not data.get('country'):
        return JsonResponse({'error': 'País es requerido'}, status=400)
    
    if not data.get('birth_date'):
        return JsonResponse({'error': 'Fecha de nacimiento es requerida'}, status=400)
    
    # Validar unicidad de username
    if User.objects.filter(username=username).exclude(id=request.user.id).exists():
        return JsonResponse({'error': 'El nombre de usuario ya está en uso'}, status=400)
    
    # Parsear fecha
    try:
        birth_date = datetime.strptime(data['birth_date'], '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}, status=400)
    
    user = request.user
    user.username = username
    user.first_name = data['first_name']
    user.last_name = data['last_name']
    user.phone = data.get('phone', '')
    user.address = data.get('address', '')
    user.country = data['country']
    user.birth_date = birth_date
    
    try:
        user.save(update_fields=['username', 'first_name', 'last_name', 'phone', 'address', 'country', 'birth_date'])
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}")
        return JsonResponse({'error': 'Error al actualizar perfil'}, status=500)
    
    return JsonResponse({
        'message': 'Perfil actualizado correctamente',
        'user': user_to_response(user)
    })


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def update_email_password(request):
    """Actualizar email y/o contraseña"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    current_password = data.get('current_password', '')
    new_email = data.get('new_email', '').lower()
    new_password = data.get('new_password', '')
    
    if not new_email and not new_password:
        return JsonResponse({'error': 'Debe proporcionar al menos un nuevo email o contraseña'}, status=400)
    
    user = request.user
    
    # Verificar contraseña actual
    if not check_password(current_password, user.password):
        return JsonResponse({'error': 'Contraseña actual incorrecta'}, status=400)
    
    with transaction.atomic():
        # Actualizar email
        if new_email:
            if '@' not in new_email or '.' not in new_email:
                return JsonResponse({'error': 'Email inválido'}, status=400)
            
            if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                return JsonResponse({'error': 'El email ya está en uso'}, status=400)
            
            user.email = new_email
        
        # Actualizar contraseña
        if new_password:
            if len(new_password) < 6:
                return JsonResponse({'error': 'La nueva contraseña debe tener al menos 6 caracteres'}, status=400)
            user.password = make_password(new_password)
        
        user.save()
    
    # Mensaje apropiado
    if new_email and new_password:
        message = "Email y contraseña actualizados correctamente"
    elif new_email:
        message = "Email actualizado correctamente"
    else:
        message = "Contraseña actualizada correctamente"
    
    return JsonResponse({
        'message': message,
        'user': user_to_response(user)
    })


@csrf_exempt
@require_http_methods(["POST"])
@login_required
def update_guest_profile(request):
    """Convertir guest a usuario regular"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    user = request.user
    
    # Verificar rol
    if user.role != 'guest':
        return JsonResponse({'error': 'Esta función solo está disponible para usuarios guest'}, status=400)
    
    # Validaciones
    username = data.get('username', '').strip()
    if not username or len(username) < 3 or len(username) > 30:
        return JsonResponse({'error': 'Username debe tener entre 3 y 30 caracteres'}, status=400)
    
    email = data.get('email', '').strip().lower()
    if not email or '@' not in email or '.' not in email:
        return JsonResponse({'error': 'Email inválido'}, status=400)
    
    if not data.get('first_name'):
        return JsonResponse({'error': 'Nombre es requerido'}, status=400)
    
    if not data.get('last_name'):
        return JsonResponse({'error': 'Apellido es requerido'}, status=400)
    
    if not data.get('country'):
        return JsonResponse({'error': 'País es requerido'}, status=400)
    
    new_password = data.get('new_password', '')
    if not new_password or len(new_password) < 6:
        return JsonResponse({'error': 'La contraseña debe tener al menos 6 caracteres'}, status=400)
    
    # Parsear fecha
    try:
        birth_date = datetime.strptime(data['birth_date'], '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}, status=400)
    
    # Validar unicidad
    if User.objects.filter(username=username).exclude(id=user.id).exists():
        return JsonResponse({'error': 'El nombre de usuario ya está en uso'}, status=400)
    
    if User.objects.filter(email=email).exclude(id=user.id).exists():
        return JsonResponse({'error': 'El email ya está en uso'}, status=400)
    
    with transaction.atomic():
        user.username = username
        user.email = email
        user.first_name = data['first_name']
        user.last_name = data['last_name']
        user.phone = data.get('phone', '')
        user.address = data.get('address', '')
        user.country = data['country']
        user.birth_date = birth_date
        user.role = 'user'
        user.password = make_password(new_password)
        user.save()
    
    return JsonResponse({
        'message': 'Perfil actualizado correctamente. Ahora eres un usuario permanente.',
        'user': user_to_response(user)
    })


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def deactivate_account(request):
    """Desactivar cuenta propia"""
    user = request.user
    
    # Proteger admin principal
    if user.id == 1:
        return JsonResponse({'error': 'No se puede desactivar la cuenta de administrador principal'}, status=400)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    current_password = data.get('current_password', '')
    confirm_text = data.get('confirm_text', '')
    
    expected_text = "CONFIRMAR ELIMINAR CUENTA"
    if confirm_text != expected_text:
        return JsonResponse({'error': f'Debes escribir "{expected_text}" para confirmar'}, status=400)
    
    if not check_password(current_password, user.password):
        return JsonResponse({'error': 'Contraseña actual incorrecta'}, status=400)
    
    # Buscar admin para transferencia
    admin_user = User.objects.filter(role='admin', is_active=True).exclude(id=user.id).order_by('id').first()
    
    if not admin_user:
        admin_user = User.objects.filter(role='admin').exclude(id=user.id).order_by('id').first()
        
        if not admin_user:
            return JsonResponse({
                'error': 'No hay administradores disponibles. Contacte con soporte técnico.'
            }, status=500)
    
    with transaction.atomic():
        # Transferir datos
        from apps.test.models import Test
        tests_transferred = Test.objects.filter(created_by=user.id).update(created_by=admin_user.pk)
        
        Result.objects.filter(user_id=user.id).update(user_id=admin_user.pk)
        
        from admin_panel.models import UserQuota
        UserQuota.objects.filter(user_id=user.id).delete()
        
        TestInvitation.objects.filter(invited_by_id=user.id).delete()
        
        # Anonimizar
        user.username = f"del_{user.username}_{user.id}"
        email_local = user.email.split('@')[0] if '@' in user.email else user.username
        user.email = f"{email_local}_{user.id}@deleted.local"
        user.role = 'deleted'
        user.first_name = 'Deleted'
        user.last_name = 'User'
        user.phone = ''
        user.address = ''
        user.country = ''
        user.birth_date = None
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save()
    
    # Cerrar sesión
    django_logout(request)
    
    return JsonResponse({
        'message': 'Tu cuenta ha sido desactivada correctamente.',
        'details': {
            'tests_transferred': tests_transferred,
            'transferred_to_admin_id': admin_user.pk,
            'transferred_to_admin_username': admin_user.username
        }
    })


# ============== DASHBOARD Y RANKINGS ==============

@require_http_methods(["GET"])
@login_required
def get_dashboard_data(request):
    """Obtiene datos del dashboard del usuario"""
    data_service = DataService()
    
    personal_data = data_service.get_personal_data(request.user.id)
    level_data = data_service.get_personal_level_data(request.user.id)
    total_active_users = data_service.get_active_users_count()
    
    return JsonResponse({
        'personal_data': personal_data,
        'level_data': level_data,
        'total_active_users': total_active_users
    })


@require_http_methods(["GET"])
@login_required
def get_rankings(request):
    """Obtiene rankings y posición del usuario"""
    limit = min(max(int(request.GET.get('limit', 10)), 1), 50)  # Limitar entre 1 y 50
    
    data_service = DataService()
    
    response = {
        'top_by_tests': data_service.get_top_by_metric('top_by_tests', limit),
        'top_by_avg_time_taken_per_question': {
            'all_attempts': data_service.get_top_by_avg_time('all', limit),
            'first_attempt': data_service.get_top_by_avg_time('first', limit)
        },
        'top_by_accuracy': {
            'all_attempts': data_service.get_top_by_accuracy('all', limit),
            'first_attempt': data_service.get_top_by_accuracy('first', limit)
        },
        'top_by_questions_answered': {
            'all_attempts': data_service.get_top_by_questions_answered('all', limit),
            'first_attempt': data_service.get_top_by_questions_answered('first', limit)
        },
        'top_by_levels': {},
        'top_by_levels_accuracy': {},
        'current_user_position': data_service.get_user_all_ranking_positions(request.user.id),
        'community_averages': data_service.get_community_averages(),
        'min_tests_for_ranking': MIN_TESTS_FOR_RANKING
    }
    
    # Rankings por nivel
    for level in PREDEFINED_LEVELS:
        response['top_by_levels'][level] = data_service.get_top_by_metric('top_by_level', limit, level)
        response['top_by_levels_accuracy'][level] = data_service.get_top_by_metric('top_by_levels_accuracy', limit, level)
    
    return JsonResponse(response)


# ============== ADMINISTRACIÓN DE USUARIOS ==============

@require_http_methods(["GET"])
@admin_required
def get_user_by_id(request, user_id):
    """Obtener usuario por ID"""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    
    return JsonResponse({'user': user_to_response(user)})


@require_http_methods(["GET"])
@admin_required
def get_user_profile(request, user_id):
    """Obtener perfil de usuario"""
    try:
        user = User.objects.values(
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'address', 'country', 'birth_date', 'role',
            'registered_at', 'login_at'
        ).get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    
    # Formatear fechas
    for field in ['birth_date', 'registered_at', 'login_at']:
        if user[field]:
            user[field] = user[field].isoformat()
    
    return JsonResponse({'user': user})


@csrf_exempt
@require_http_methods(["PUT", "PATCH"])
@admin_required
def update_user(request, user_id):
    """Actualizar usuario (admin)"""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    # Actualizar campos permitidos
    updatable_fields = ['first_name', 'last_name', 'email', 'phone', 'address', 'country', 'role']
    
    for field in updatable_fields:
        if field in data and data[field]:
            if field == 'email':
                value = data[field].lower()
                if User.objects.filter(email=value).exclude(id=user.pk).exists():
                    return JsonResponse({'error': 'El email ya está en uso'}, status=400)
            elif field == 'role' and data[field] not in ['user', 'admin']:
                continue
            else:
                value = data[field]
            setattr(user, field, value)
    
    if 'birth_date' in data and data['birth_date']:
        try:
            user.birth_date = datetime.strptime(data['birth_date'], '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Formato de fecha inválido. Use YYYY-MM-DD'}, status=400)
    
    try:
        user.save()
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {str(e)}")
        return JsonResponse({'error': 'Error al actualizar usuario'}, status=500)
    
    return JsonResponse({
        'user': user_to_response(user),
        'message': 'Usuario actualizado correctamente'
    })


@require_http_methods(["GET"])
@admin_required
def get_users_with_stats(request):
    """Obtener usuarios con estadísticas (paginado)"""
    # Parámetros con valores por defecto y validación
    page = max(int(request.GET.get('page', 1)), 1)
    page_size = min(max(int(request.GET.get('page_size', 10)), 1), 100)
    sort_by = request.GET.get('sort_by', 'registered_at')
    sort_order = request.GET.get('sort_order', 'desc')
    role = request.GET.get('role', '')
    search = request.GET.get('search', '')
    
    valid_sort_fields = ['id', 'username', 'email', 'role', 'registered_at', 'login_at']
    if sort_by not in valid_sort_fields:
        sort_by = 'registered_at'
    
    # Query base con anotaciones optimizadas
    users_with_stats = User.objects.annotate(
        tests_completed=Coalesce(Count('results', filter=Q(results__status='completed')), Value(0)),
        tests_in_progress=Coalesce(Count('results', filter=Q(results__status='in_progress')), Value(0)),
        average_score=Coalesce(
            Avg(Case(When(results__status='completed', then=Cast(
                F('results__correct_answers') * 100.0 / 
                (F('results__correct_answers') + F('results__wrong_answers')),
                FloatField()
            )))),
            Value(0.0)
        ),
        total_tests_taken=Coalesce(Count('results'), Value(0))
    )
    
    # Aplicar filtros
    if role:
        users_with_stats = users_with_stats.filter(role=role)
    
    if search:
        users_with_stats = users_with_stats.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    
    total_filtered = users_with_stats.count()
    
    # Ordenar y paginar
    order_prefix = '-' if sort_order == 'desc' else ''
    users_with_stats = users_with_stats.order_by(f'{order_prefix}{sort_by}')
    
    start = (page - 1) * page_size
    users_paginated = users_with_stats[start:start + page_size]
    
    from apps.test.models import Test
    total_tests_count = Test.objects.count()
    
    users_data = []
    for user in users_paginated:
        users_data.append({
            'id': user.pk,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': user.phone,
            'address': user.address,
            'country': user.country,
            'birth_date': user.birth_date.isoformat() if user.birth_date else None,
            'role': user.role,
            'registered_at': user.registered_at.isoformat() if user.registered_at else None,
            'login_at': user.login_at.isoformat() if user.login_at else None,
            'tests_completed': getattr(user, 'tests_completed', 0),
            'tests_in_progress': getattr(user, 'tests_in_progress', 0),
            'tests_not_started': total_tests_count - getattr(user, 'total_tests_taken', 0),
            'average_score': round(getattr(user, 'average_score', 0.0), 2),
            'total_tests_taken': getattr(user, 'total_tests_taken', 0),
        })
    
    return JsonResponse({
        'users': users_data,
        'stats': {
            'total_users': User.objects.count(),
            'total_filtered_users': total_filtered,
        },
        'filters': {
            'page': page,
            'page_size': page_size,
            'role': role,
            'search': search,
            'sort_by': sort_by,
            'sort_order': sort_order,
        }
    })


@csrf_exempt
@require_http_methods(["DELETE"])
@admin_required
def delete_user(request, user_id):
    """Eliminar usuario permanentemente (admin)"""
    user_id = int(user_id)
    
    # Proteger admin principal
    if user_id == 1:
        return JsonResponse({'error': 'No se puede eliminar el administrador principal'}, status=400)
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)
    
    # Verificar que no sea el único admin
    if user.role == 'admin':
        admin_count = User.objects.filter(role='admin', is_active=True).count()
        if admin_count <= 1:
            return JsonResponse({'error': 'No se puede eliminar el único administrador activo'}, status=400)
    
    with transaction.atomic():
        # Limpiar datos relacionados
        PasswordResetToken.objects.filter(user_id=user_id).delete()
        
        from apps.test.models import Test
        Test.objects.filter(created_by=user_id).update(created_by=1)
        
        Result.objects.filter(user_id=user_id).update(user_id=1)
        
        TestInvitation.objects.filter(invited_by_id=user_id).delete()
        TestInvitation.objects.filter(guest_user_id=user_id).update(guest_user=None)
        
        # Eliminar usuario
        user.delete()
    
    return JsonResponse({
        'message': 'Usuario eliminado permanentemente',
        'deleted_user_id': user_id,
        'deleted_username': user.username
    })