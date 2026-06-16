# apps/invitations/views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q
from django.utils import timezone
from django.db import transaction
from django.core.paginator import Paginator  # FIX: was missing
from functools import wraps
from datetime import datetime, timedelta  # FIX: datetime was missing
import json
import logging

from .models import TestInvitation, InvitationEvent
from apps.accounts.models import User
from .serializers import (
    CreateInvitationSerializer, AcceptInvitationSerializer,
    InvitationSerializer, InvitationResponseSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'user') or not request.user or not request.user.is_authenticated:
            return JsonResponse({'error': 'usuario no autenticado'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'user') or not request.user or not request.user.is_authenticated:
            return JsonResponse({'error': 'usuario no autenticado'}, status=401)
        if request.user.role != 'admin':
            return JsonResponse({'error': 'Acceso denegado. Se requieren privilegios de administrador'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def authenticate_user(response, user, is_guest=False):
    """Configura la cookie de autenticación para el usuario"""
    from ..accounts.views import set_auth_cookie
    return set_auth_cookie(response, user, is_guest)


def transfer_guest_results(guest_user_id, new_user_id, test_id):
    """Transfiere resultados de guest a usuario regular"""
    from apps.results.models import Result

    updated = Result.objects.filter(
        user_id=guest_user_id,
        test_id=test_id,
    ).update(user_id=new_user_id)

    # Delete guest if they have no remaining results
    if not Result.objects.filter(user_id=guest_user_id).exists():
        User.objects.filter(id=guest_user_id).delete()

    return updated


def create_guest_user():
    """Crea un usuario guest temporal"""
    from django.contrib.auth.hashers import make_password
    import secrets

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    username = f"guest_{timestamp}_{secrets.token_hex(4)}"
    temp_password = secrets.token_hex(8)

    return User.objects.create(
        username=username,
        email=f"{username}@guest.temp",
        password=make_password(temp_password),
        first_name="Invitado",
        role="guest",
        birth_date=timezone.now().date().replace(year=timezone.now().year - 18),
    )


def log_invitation_event(invitation, event_type, user=None, metadata=None):
    """Registra un evento de invitación"""
    InvitationEvent.objects.create(
        invitation=invitation,
        event_type=event_type,
        user=user,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Public views
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def create_invitation(request):
    """Crea una nueva invitación a un test"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    serializer = CreateInvitationSerializer(data=data)
    if not serializer.is_valid():
        return JsonResponse({'error': serializer.errors}, status=400)

    test_id = serializer.validated_data['test_id']
    message = serializer.validated_data.get('message', '')

    from apps.test.models import Test
    try:
        test = Test.objects.get(id=test_id, is_active=True)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)

    invitation = TestInvitation.objects.create(
        test=test,
        invited_by=request.user,
        message=message,
    )
    log_invitation_event(invitation, 'created', request.user)

    return JsonResponse({
        'invitation': InvitationSerializer(invitation).data,
        'invitation_url': invitation.invitation_url,
        'message': 'Invitación creada exitosamente',
    }, status=201)


@require_http_methods(["GET"])
def check_invitation(request):
    """Verifica el estado de una invitación"""
    token = request.GET.get('token')
    if not token:
        return JsonResponse({'error': 'token de invitación requerido'}, status=400)

    try:
        invitation = TestInvitation.objects.select_related(
            'test', 'invited_by', 'guest_user'
        ).get(token=token, expires_at__gt=timezone.now())
    except TestInvitation.DoesNotExist:
        return JsonResponse({'error': 'invitación no válida o expirada'}, status=404)

    log_invitation_event(
        invitation, 'viewed',
        request.user if request.user.is_authenticated else None,
    )

    response_data = InvitationResponseSerializer(invitation).data

    current_user_id = request.user.id if request.user.is_authenticated else 0

    if invitation.guest_user:
        result_user_id = invitation.guest_user.id
    elif current_user_id:
        result_user_id = current_user_id
    else:
        result_user_id = None

    if result_user_id:
        from apps.results.models import Result
        existing_result = Result.objects.filter(
            user_id=result_user_id,
            test_id=invitation.test.id,
        ).order_by('-updated_at').first()

        if existing_result:
            # FIX: serialize datetimes to isoformat strings
            response_data['result'] = {
                'id': existing_result.pk,
                'status': existing_result.status,
                'score': existing_result.score_percentage,
                'started_at': existing_result.started_at.isoformat(),
                'completed_at': existing_result.updated_at.isoformat(),
                'updated_at': existing_result.updated_at.isoformat(),
            }

    response_data['is_authenticated'] = request.user.is_authenticated
    response_data['current_user_id'] = current_user_id

    return JsonResponse(response_data)


@csrf_exempt
@require_http_methods(["POST"])
def accept_invitation(request):
    """Acepta una invitación – retorna JWT para autenticación"""
    token = request.GET.get('token')
    if not token:
        return JsonResponse({'error': 'token de invitación requerido'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    serializer = AcceptInvitationSerializer(data=data)
    if not serializer.is_valid():
        return JsonResponse({'error': serializer.errors}, status=400)

    as_guest = serializer.validated_data.get('as_guest', False)

    try:
        invitation = TestInvitation.objects.select_related(
            'test', 'invited_by', 'guest_user'
        ).get(token=token, expires_at__gt=timezone.now())
    except TestInvitation.DoesNotExist:
        return JsonResponse({'error': 'invitación no válida o expirada'}, status=404)

    current_user = request.user if request.user.is_authenticated else None
    current_user_id = current_user.id if current_user else 0

    response_data = {
        'test_id': invitation.test.id,
        'invitation_id': invitation.pk,
    }
    authenticated_user = None

    # --- Caso A: ya hay guest_user asignado -----------------------------------
    if invitation.guest_user:
        guest_user_id = invitation.guest_user.pk

        # A1: el usuario autenticado ES el guest
        if current_user_id == guest_user_id:
            invitation.is_used = True
            if invitation.is_guest and current_user and current_user.role == 'user':
                invitation.is_guest = False
            invitation.save()
            log_invitation_event(invitation, 'accepted', current_user)
            authenticated_user = current_user
            response_data.update({
                'user_id': current_user_id,
                'is_guest': invitation.is_guest,
                'message': 'Continuando con tu usuario',
            })

        # A2: usuario autenticado diferente con role 'user'
        elif current_user and current_user.role == 'user':
            with transaction.atomic():
                transferred = transfer_guest_results(guest_user_id, current_user_id, invitation.test.id)
                invitation.guest_user = current_user
                invitation.is_guest = False
                invitation.is_used = True
                invitation.save()
                log_invitation_event(invitation, 'accepted', current_user, {
                    'transferred_from_guest': guest_user_id,
                    'results_transferred': transferred,
                })
            authenticated_user = current_user
            response_data.update({
                'user_id': current_user_id,
                'is_guest': False,
                'transferred_from_guest': True,
                'message': 'Test asignado a tu cuenta',
            })

        # A3: no autenticado – re-autenticar al guest existente
        else:
            from django.contrib.auth import get_user_model
            _User = get_user_model()
            try:
                guest_user = _User.objects.get(id=guest_user_id)
            except _User.DoesNotExist:
                return JsonResponse({'error': 'Usuario guest no encontrado', 'requires_login': True}, status=404)

            invitation.is_used = True
            invitation.save()
            log_invitation_event(invitation, 'accepted', guest_user, {'auto_authenticated': True})
            authenticated_user = guest_user
            response_data.update({
                'user_id': guest_user_id,
                'is_guest': invitation.is_guest,
                'auto_authenticated': True,
                'message': 'Autenticado automáticamente como usuario invitado',
            })

    # --- Caso B: no hay guest_user asignado ----------------------------------
    else:
        # B1: usuario autenticado
        if current_user:
            with transaction.atomic():
                invitation.guest_user = current_user
                invitation.is_guest = (current_user.role == 'guest')
                invitation.is_used = True
                invitation.save()
                log_invitation_event(invitation, 'accepted', current_user)
            authenticated_user = current_user
            response_data.update({
                'user_id': current_user_id,
                'is_guest': invitation.is_guest,
                'message': 'Test asignado a tu cuenta',
            })

        # B2: crear guest
        elif as_guest:
            with transaction.atomic():
                guest_user = create_guest_user()
                invitation.guest_user = guest_user
                invitation.is_guest = True
                invitation.is_used = True
                invitation.save()
                log_invitation_event(invitation, 'accepted', guest_user, {'created_as_guest': True})
            authenticated_user = guest_user
            response_data.update({
                'user_id': guest_user.pk,
                'is_guest': True,
                'auto_authenticated': True,
                'message': 'Cuenta de invitado creada',
            })

        # B3: requiere login
        else:
            return JsonResponse({
                'error': 'Inicia sesión para aceptar la invitación',
                'requires_login': True,
            }, status=401)

    # --- Emitir JWT ----------------------------------------------------------
    if authenticated_user:
        from apps.accounts.views import generate_jwt_token
        from apps.accounts.serializers import UserResponseSerializer

        jwt_token = generate_jwt_token(
            authenticated_user,
            is_guest=(authenticated_user.role == 'guest'),  # type: ignore
        )
        response_data['access_token'] = jwt_token
        response_data['token_type'] = 'Bearer'
        response_data['user'] = UserResponseSerializer(authenticated_user).data

    return JsonResponse(response_data)


@require_http_methods(["GET"])
@login_required
def get_user_invitations(request):
    """Obtiene las invitaciones creadas por el usuario"""
    invitations = TestInvitation.objects.select_related(
        'test', 'invited_by', 'guest_user'
    ).filter(invited_by=request.user).order_by('-created_at')

    return JsonResponse({'invitations': InvitationSerializer(invitations, many=True).data})


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
@admin_required
def admin_get_invitations(request):
    """Obtener todas las invitaciones con filtros y paginación"""

    page = max(1, int(request.GET.get('page', 1)))
    page_size = int(request.GET.get('page_size', 20))
    if page_size < 1 or page_size > 100:
        page_size = 20

    sort_by = request.GET.get('sort_by', 'created_at')
    sort_order = request.GET.get('sort_order', 'desc')

    search = request.GET.get('search', '')
    test_id = request.GET.get('test_id')
    invited_by = request.GET.get('invited_by')
    is_used_param = request.GET.get('is_used')
    is_guest_param = request.GET.get('is_guest')
    status = request.GET.get('status')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    valid_sort_fields = ['id', 'test_id', 'invited_by', 'is_used', 'is_guest',
                         'expires_at', 'created_at']
    if sort_by not in valid_sort_fields:
        sort_by = 'created_at'
    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc'

    qs = TestInvitation.objects.select_related('test', 'invited_by', 'guest_user')

    if search:
        qs = qs.filter(Q(message__icontains=search) | Q(token__icontains=search))

    if test_id:
        try:
            qs = qs.filter(test_id=int(test_id))
        except ValueError:
            pass

    if invited_by:
        try:
            qs = qs.filter(invited_by_id=int(invited_by))
        except ValueError:
            pass

    if is_used_param is not None:
        qs = qs.filter(is_used=is_used_param.lower() == 'true')

    if is_guest_param is not None:
        qs = qs.filter(is_guest=is_guest_param.lower() == 'true')

    now = timezone.now()
    if status == 'active':
        qs = qs.filter(is_used=False, expires_at__gt=now)
    elif status == 'used':
        qs = qs.filter(is_used=True)
    elif status == 'expired':
        qs = qs.filter(expires_at__lte=now)

    # FIX: datetime was not imported before
    if start_date:
        try:
            qs = qs.filter(created_at__date__gte=datetime.strptime(start_date, '%Y-%m-%d').date())
        except ValueError:
            pass

    if end_date:
        try:
            qs = qs.filter(created_at__date__lte=datetime.strptime(end_date, '%Y-%m-%d').date())
        except ValueError:
            pass

    total_invitations = TestInvitation.objects.count()
    total_filtered = qs.count()

    order_prefix = '-' if sort_order == 'desc' else ''
    qs = qs.order_by(f'{order_prefix}{sort_by}')

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    # FIX: use model property instead of duplicating status logic
    invitations_data = [
        {
            'id': inv.id,
            'test_id': inv.test.id,
            'test_title': inv.test.title,
            'invited_by': inv.invited_by.id,
            'inviter_name': inv.invited_by.username,
            'message': inv.message,
            'token': inv.token,
            'is_used': inv.is_used,
            'is_guest': inv.is_guest,
            'guest_user_id': inv.guest_user.id if inv.guest_user else None,
            'guest_name': inv.guest_user.username if inv.guest_user else None,
            'expires_at': inv.expires_at.isoformat(),
            'created_at': inv.created_at.isoformat(),
            'status': inv.status,          # delegates to model property
            'invitation_url': inv.invitation_url,
        }
        for inv in page_obj
    ]

    return JsonResponse({
        'invitations': invitations_data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_items': total_filtered,
            'total_pages': paginator.num_pages,
        },
        'filters_applied': {
            'page': page,
            'page_size': page_size,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'search': search,
            'test_id': test_id,
            'invited_by': invited_by,
            'is_used': is_used_param,
            'is_guest': is_guest_param,
            'status': status,
            'start_date': start_date,
            'end_date': end_date,
        },
        'available_filters': {
            'total_invitations': total_invitations,
        },
    })


@csrf_exempt
@require_http_methods(["DELETE"])
@admin_required
def admin_delete_invitation(request, invitation_id):
    """Eliminar una invitación específica"""
    try:
        invitation = TestInvitation.objects.get(id=invitation_id)
    except TestInvitation.DoesNotExist:
        return JsonResponse({'error': 'invitación no encontrada'}, status=404)

    if invitation.is_used:
        return JsonResponse({'error': 'no se puede eliminar una invitación usada'}, status=400)

    invitation.delete()
    return JsonResponse({'message': 'Invitación eliminada exitosamente', 'id': invitation_id})


@csrf_exempt
@require_http_methods(["DELETE"])
@admin_required
def admin_delete_invitations_bulk(request):
    """Eliminar múltiples invitaciones"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return JsonResponse({'error': 'Se requiere una lista de IDs con al menos un elemento'}, status=400)

    try:
        ids = [int(v) for v in ids]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Los IDs deben ser números enteros'}, status=400)

    used_count = TestInvitation.objects.filter(id__in=ids, is_used=True).count()
    if used_count > 0:
        return JsonResponse({
            'error': 'una o más invitaciones ya están usadas y no pueden ser eliminadas'
        }, status=400)

    deleted_count, _ = TestInvitation.objects.filter(id__in=ids).delete()
    return JsonResponse({
        'message': 'Invitaciones eliminadas exitosamente',
        'deleted_count': deleted_count,
        'deleted_ids': ids,
    })


@require_http_methods(["GET"])
@admin_required
def admin_get_invitation_stats(request):
    """Obtener estadísticas de invitaciones"""
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    # FIX: 5 separate COUNT queries → 1 aggregate
    agg = TestInvitation.objects.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(is_used=False, expires_at__gt=now)),
        used=Count('id', filter=Q(is_used=True)),
        expired=Count('id', filter=Q(expires_at__lte=now)),
        with_guest=Count('id', filter=Q(guest_user__isnull=False)),
    )
    stats = {
        'total': agg['total'],
        'active': agg['active'],
        'used': agg['used'],
        'expired': agg['expired'],
        'with_guest': agg['with_guest'],
    }

    test_stats = list(
        TestInvitation.objects.values('test__id', 'test__title')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    user_stats = list(
        TestInvitation.objects.values('invited_by__id', 'invited_by__username', 'invited_by__email')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    # FIX: replace .extra() with TruncDate – portable, non-deprecated
    from django.db.models.functions import TruncDate

    def _daily_breakdown(since):
        """Returns per-day stats annotated in a single query."""
        return list(
            TestInvitation.objects
            .filter(created_at__gte=since)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(
                total=Count('id'),
                active=Count('id', filter=Q(is_used=False, expires_at__gt=now)),
                used=Count('id', filter=Q(is_used=True)),
                expired=Count('id', filter=Q(expires_at__lte=now)),
            )
            .order_by('day')
        )

    def _format_daily(rows):
        return [
            {
                'date': row['day'].isoformat() if row['day'] else None,
                'total': row['total'],
                'active': row['active'],
                'used': row['used'],
                'expired': row['expired'],
            }
            for row in rows
        ]

    # FIX: compute both periods in two queries instead of four
    rows_30 = _daily_breakdown(thirty_days_ago)
    rows_7 = [r for r in rows_30 if r['day'] and r['day'] >= seven_days_ago.date()]

    return JsonResponse({
        'stats': stats,
        'by_test': test_stats,
        'by_user': user_stats,
        'daily_last_30_days': [
            {'date': r['day'].isoformat() if r['day'] else None, 'count': r['total']}
            for r in rows_30
        ],
        'status_over_time': {
            'last_7_days': _format_daily(rows_7),
            'last_30_days': _format_daily(rows_30),
        },
        'timestamp': now.isoformat(),
    })


@require_http_methods(["GET"])
@admin_required
def admin_get_invitation_detail(request, invitation_id):
    """Obtener detalle completo de una invitación"""
    try:
        invitation = TestInvitation.objects.select_related(
            'test', 'invited_by', 'guest_user'
        ).prefetch_related('test__questions').get(id=invitation_id)
    except TestInvitation.DoesNotExist:
        return JsonResponse({'error': 'invitación no encontrada'}, status=404)

    now = timezone.now()
    inv_status = invitation.status  # use model property

    # FIX: 2 queries → 1 aggregate
    guest_stats = None
    if invitation.guest_user:
        from apps.results.models import Result
        agg = Result.objects.filter(user=invitation.guest_user).aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
        )
        guest_stats = {
            'total_tests_taken': agg['total'],
            'completed_tests': agg['completed'],
        }

    response_data = {
        'id': invitation.pk,
        'test': {
            'id': invitation.test.id,
            'title': invitation.test.title,
            'description': invitation.test.description,
            'main_topic': invitation.test.main_topic,
            'sub_topic': invitation.test.sub_topic,
            'specific_topic': invitation.test.specific_topic,
            'level': invitation.test.level,
            # FIX: questions prefetched so .count() hits the cache, not the DB
            'total_questions': invitation.test.questions.count(),
        },
        'inviter': {
            'id': invitation.invited_by.id,
            'username': invitation.invited_by.username,
            'email': invitation.invited_by.email,
            'first_name': invitation.invited_by.first_name,
            'last_name': invitation.invited_by.last_name,
        },
        'guest_user': {
            'id': invitation.guest_user.id,
            'username': invitation.guest_user.username,
            'email': invitation.guest_user.email,
            'first_name': invitation.guest_user.first_name,
            'last_name': invitation.guest_user.last_name,
        } if invitation.guest_user else None,
        'guest_stats': guest_stats,
        'message': invitation.message,
        'token': invitation.token,
        'is_used': invitation.is_used,
        'is_guest': invitation.is_guest,
        'expires_at': invitation.expires_at.isoformat(),
        'created_at': invitation.created_at.isoformat(),
        'status': inv_status,
        'invitation_url': invitation.invitation_url,
        'time_until_expiry': None,
        'time_since_created': None,
    }

    if inv_status == 'active':
        delta = invitation.expires_at - now
        response_data['time_until_expiry'] = {
            'days': delta.days,
            'hours': delta.seconds // 3600,
            'minutes': (delta.seconds % 3600) // 60,
        }

    delta = now - invitation.created_at
    response_data['time_since_created'] = {
        'days': delta.days,
        'hours': delta.seconds // 3600,
        'minutes': (delta.seconds % 3600) // 60,
    }

    return JsonResponse(response_data)