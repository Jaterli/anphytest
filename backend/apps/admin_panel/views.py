# admin_panel/views.py
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Count, Avg, Q, F, Sum, ExpressionWrapper, IntegerField
from django.utils import timezone
from functools import wraps
import csv
import json
import logging

from apps.admin_panel.models import UserQuota, SystemConfig
from apps.test.models import Test
from apps.results.models import Result
from apps.accounts.models import User
from django.core.paginator import Paginator
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

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
# Helper: serialise a UserQuota instance to dict
# ---------------------------------------------------------------------------

def _quota_to_dict(quota):
    return {
        'id': quota.id,
        'user_id': quota.user.id,
        'username': quota.user.username,
        'user_email': quota.user.email,
        'month_year': quota.month_year,
        'max_requests': quota.max_requests,
        'used_requests': quota.used_requests,
        'remaining_requests': quota.remaining_requests,
        'usage_percentage': quota.usage_percentage,
        'status': quota.status,
        'created_at': quota.created_at.isoformat(),
        'updated_at': quota.updated_at.isoformat(),
    }


def _config_to_dict(config):
    return {
        'id': config.id,
        'key': config.key,
        'value': config.value,
        'description': config.description,
        'created_at': config.created_at.isoformat(),
        'updated_at': config.updated_at.isoformat(),
    }


# ===========================================================================
# User Quota views
# ===========================================================================

@require_http_methods(["GET"])
@admin_required
def admin_get_user_quotas(request):
    """Obtener todas las cuotas de usuarios con filtros y paginación"""

    # --- query params -------------------------------------------------------
    page = max(1, int(request.GET.get('page', 1)))
    page_size = int(request.GET.get('page_size', 20))
    if page_size < 1 or page_size > 100:
        page_size = 20

    sort_by = request.GET.get('sort_by', 'month_year')
    sort_order = request.GET.get('sort_order', 'desc')

    search = request.GET.get('search', '')
    user_id = request.GET.get('user_id')
    month_year = request.GET.get('month_year')
    min_remaining = request.GET.get('min_remaining')
    max_usage = request.GET.get('max_usage')
    min_requests = request.GET.get('min_requests')
    max_requests_param = request.GET.get('max_requests')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    valid_sort_fields = ['id', 'user_id', 'month_year', 'max_requests',
                         'used_requests', 'created_at', 'updated_at']
    if sort_by not in valid_sort_fields:
        sort_by = 'month_year'
    if sort_order not in ('asc', 'desc'):
        sort_order = 'desc'

    # --- global total (before any filter) -----------------------------------
    global_total = UserQuota.objects.count()

    # --- base queryset ------------------------------------------------------
    qs = UserQuota.objects.select_related('user')

    if search:
        qs = qs.filter(
            Q(user__username__icontains=search) |
            Q(user__email__icontains=search) |
            Q(user__id__icontains=search)
        )

    if user_id:
        try:
            qs = qs.filter(user_id=int(user_id))
        except ValueError:
            pass

    if month_year:
        qs = qs.filter(month_year=month_year)

    # remaining = max_requests - used_requests  (use F-expression, DB-safe)
    if min_remaining:
        try:
            qs = qs.annotate(
                remaining=ExpressionWrapper(
                    F('max_requests') - F('used_requests'),
                    output_field=IntegerField()
                )
            ).filter(remaining__gte=int(min_remaining))
        except ValueError:
            pass

    # usage % filter – keep in DB via annotation to avoid .extra()
    if max_usage:
        try:
            max_usage_val = int(max_usage)
            qs = qs.filter(max_requests__gt=0).annotate(
                usage_pct=ExpressionWrapper(
                    F('used_requests') * 100 / F('max_requests'),
                    output_field=IntegerField()
                )
            ).filter(usage_pct__lte=max_usage_val)
        except ValueError:
            pass

    if min_requests:
        try:
            qs = qs.filter(max_requests__gte=int(min_requests))
        except ValueError:
            pass

    if max_requests_param:
        try:
            qs = qs.filter(max_requests__lte=int(max_requests_param))
        except ValueError:
            pass

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

    filtered_total = qs.count()

    order_prefix = '-' if sort_order == 'desc' else ''
    qs = qs.order_by(f'{order_prefix}{sort_by}')

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    available_months = list(
        UserQuota.objects.values_list('month_year', flat=True)
        .distinct().order_by('-month_year')[:12]
    ) or [datetime.now().strftime('%Y-%m')]

    return JsonResponse({
        'quotas': [_quota_to_dict(q) for q in page_obj],
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_items': filtered_total,
            'total_pages': paginator.num_pages,
        },
        'filters_applied': {
            'page': page,
            'page_size': page_size,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'search': search,
            'user_id': user_id,
            'month_year': month_year,
            'min_remaining': min_remaining,
            'max_usage': max_usage,
            'min_requests': min_requests,
            'max_requests': max_requests_param,
            'start_date': start_date,
            'end_date': end_date,
        },
        'available_filters': {
            'total_quotas': global_total,
            'filtered_quotas': filtered_total,
            'available_months': available_months,
            'available_statuses': ['normal', 'warning', 'critical', 'exceeded'],
            'default_max_requests': 5,
        },
    })


@require_http_methods(["GET"])
@admin_required
def admin_get_user_quota(request, user_id):
    """Obtener cuota de un usuario específico"""
    month_year = request.GET.get('month_year')

    qs = UserQuota.objects.select_related('user').filter(user_id=user_id)
    if month_year:
        qs = qs.filter(month_year=month_year)
    else:
        qs = qs.order_by('-month_year')

    quota = qs.first()
    if not quota:
        return JsonResponse({'error': 'cuota no encontrada'}, status=404)

    return JsonResponse({'quota': _quota_to_dict(quota)})


@require_http_methods(["GET"])
@admin_required
def admin_get_quota_stats(request):
    """Obtener estadísticas globales de cuotas"""

    # Annotate usage percentage at DB level to avoid .extra(having=...)
    annotated = UserQuota.objects.filter(max_requests__gt=0).annotate(
        usage_pct=ExpressionWrapper(
            F('used_requests') * 100 / F('max_requests'),
            output_field=IntegerField()
        )
    )

    stats = {
        'total_users_with_quota': UserQuota.objects.values('user_id').distinct().count(),
        'total_requests_allowed': UserQuota.objects.aggregate(total=Sum('max_requests'))['total'] or 0,
        'total_requests_used': UserQuota.objects.aggregate(total=Sum('used_requests'))['total'] or 0,
        'users_exceeding_quota': UserQuota.objects.filter(
            used_requests__gt=F('max_requests')
        ).values('user_id').distinct().count(),
        # critical: 80 % <= usage < 100 %
        'users_critical': annotated.filter(
            usage_pct__gte=80, usage_pct__lt=100
        ).values('user_id').distinct().count(),
        # warning: 50 % <= usage < 80 %
        'users_warning': annotated.filter(
            usage_pct__gte=50, usage_pct__lt=80
        ).values('user_id').distinct().count(),
    }

    current_month = datetime.now().strftime('%Y-%m')
    current_month_agg = UserQuota.objects.filter(month_year=current_month).aggregate(
        total_requests=Sum('max_requests'),
        used_requests=Sum('used_requests'),
    )

    monthly_stats = list(
        UserQuota.objects.values('month_year').annotate(
            total_requests=Sum('max_requests'),
            used_requests=Sum('used_requests'),
            user_count=Count('user_id', distinct=True),
        ).order_by('-month_year')[:12]
    )

    top_users = list(
        UserQuota.objects.select_related('user').values(
            'user_id', 'user__username', 'user__email'
        ).annotate(
            total_used=Sum('used_requests'),
            total_allowed=Sum('max_requests'),
        ).order_by('-total_used')[:10]
    )

    return JsonResponse({
        'stats': stats,
        'current_month': {
            'month': current_month,
            'total_requests': current_month_agg['total_requests'] or 0,
            'used_requests': current_month_agg['used_requests'] or 0,
        },
        'monthly_stats': [
            {
                'month': item['month_year'],
                'total_requests': item['total_requests'] or 0,
                'used_requests': item['used_requests'] or 0,
                'user_count': item['user_count'],
                'usage_percentage': int(
                    (item['used_requests'] or 0) * 100 / (item['total_requests'] or 1)
                ),
            }
            for item in monthly_stats
        ],
        'top_users': [
            {
                'user_id': item['user_id'],
                'username': item['user__username'],
                'email': item['user__email'],
                'total_used': item['total_used'],
                'total_allowed': item['total_allowed'],
                'usage_percentage': int(
                    item['total_used'] * 100 / (item['total_allowed'] or 1)
                ),
            }
            for item in top_users
        ],
        'timestamp': datetime.now().isoformat(),
    })


@require_http_methods(["GET"])
@admin_required
def admin_get_user_quota_months(request, user_id):
    """Obtener los meses disponibles para un usuario"""
    months = list(
        UserQuota.objects.filter(user_id=user_id)
        .values_list('month_year', flat=True)
        .distinct()
        .order_by('-month_year')
    )
    return JsonResponse({'months': months})


@csrf_exempt
@require_http_methods(["POST"])
@admin_required
def admin_create_user_quota(request):
    """Crear una nueva cuota para un usuario"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    for field in ('user_id', 'month_year', 'max_requests'):
        if field not in data:
            return JsonResponse({'error': f'{field} is required'}, status=400)

    user_id = data['user_id']
    month_year = data['month_year']

    try:
        datetime.strptime(month_year, '%Y-%m')
    except ValueError:
        return JsonResponse({'error': 'month_year debe tener formato YYYY-MM'}, status=400)

    try:
        max_requests = int(data['max_requests'])
        if max_requests < 1:
            return JsonResponse({'error': 'max_requests debe ser al menos 1'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'max_requests debe ser un número entero'}, status=400)

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'usuario no encontrado'}, status=404)

    if UserQuota.objects.filter(user_id=user_id, month_year=month_year).exists():
        return JsonResponse({'error': 'ya existe una cuota para este usuario y mes'}, status=409)

    quota = UserQuota.objects.create(
        user=user,
        month_year=month_year,
        max_requests=max_requests,
        used_requests=0,
    )

    return JsonResponse({'quota': _quota_to_dict(quota), 'message': 'Cuota creada exitosamente'}, status=201)


@csrf_exempt
@require_http_methods(["PUT", "PATCH"])
@admin_required
def admin_update_user_quota(request, quota_id):
    """Actualizar una cuota existente"""
    try:
        quota = UserQuota.objects.select_related('user').get(id=quota_id)
    except UserQuota.DoesNotExist:
        return JsonResponse({'error': 'cuota no encontrada'}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if 'max_requests' in data:
        try:
            val = int(data['max_requests'])
            if val < 1:
                return JsonResponse({'error': 'max_requests debe ser al menos 1'}, status=400)
            quota.max_requests = val
        except (ValueError, TypeError):
            return JsonResponse({'error': 'max_requests debe ser un número entero'}, status=400)

    if 'used_requests' in data:
        try:
            val = int(data['used_requests'])
            if val < 0:
                return JsonResponse({'error': 'used_requests no puede ser negativo'}, status=400)
            quota.used_requests = val
        except (ValueError, TypeError):
            return JsonResponse({'error': 'used_requests debe ser un número entero'}, status=400)

    quota.save()
    return JsonResponse({'quota': _quota_to_dict(quota), 'message': 'Cuota actualizada exitosamente'})


@require_http_methods(["DELETE"])
@admin_required
def admin_delete_user_quota(request, quota_id):
    """Eliminar una cuota"""
    try:
        quota = UserQuota.objects.get(id=quota_id)
    except UserQuota.DoesNotExist:
        return JsonResponse({'error': 'cuota no encontrada'}, status=404)

    deleted_data = {'id': quota.pk, 'user_id': quota.user.id, 'month_year': quota.month_year}
    quota.delete()
    return JsonResponse({'message': 'Cuota eliminada exitosamente', 'deleted': deleted_data})


@csrf_exempt
@require_http_methods(["POST"])
@admin_required
def admin_delete_quotas_bulk(request):
    """Eliminar múltiples cuotas"""
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

    existing_count = UserQuota.objects.filter(id__in=ids).count()
    if existing_count != len(ids):
        return JsonResponse({
            'error': 'una o más cuotas no existen',
            'found': existing_count,
            'requested': len(ids),
        }, status=404)

    deleted_count, _ = UserQuota.objects.filter(id__in=ids).delete()
    return JsonResponse({'message': 'Cuotas eliminadas exitosamente', 'deleted_count': deleted_count, 'deleted_ids': ids})


@require_http_methods(["GET"])
@admin_required
def admin_export_quotas_csv(request):
    """Exportar cuotas a CSV"""
    search = request.GET.get('search', '')
    month_year = request.GET.get('month_year')

    qs = UserQuota.objects.select_related('user')
    if search:
        qs = qs.filter(
            Q(user__username__icontains=search) | Q(user__email__icontains=search)
        )
    if month_year:
        qs = qs.filter(month_year=month_year)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="user_quotas_export.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Usuario ID', 'Usuario', 'Email', 'Mes/Año',
                     'Máx. Solicitudes', 'Usadas', 'Restantes', 'Uso (%)', 'Estado',
                     'Creada', 'Actualizada'])
    for quota in qs:
        writer.writerow([
            quota.pk, quota.user.id, quota.user.username, quota.user.email,
            quota.month_year, quota.max_requests, quota.used_requests,
            quota.remaining_requests, quota.usage_percentage, quota.status,
            quota.created_at.isoformat(), quota.updated_at.isoformat(),
        ])
    return response


# ===========================================================================
# System Config views
# ===========================================================================

@require_http_methods(["GET"])
@admin_required
def admin_get_system_configs(request):
    """Obtener todas las configuraciones del sistema"""
    configs = list(SystemConfig.objects.values(
        'id', 'key', 'value', 'description', 'created_at', 'updated_at'
    ))
    # isoformat for datetime fields
    for c in configs:
        c['created_at'] = c['created_at'].isoformat()
        c['updated_at'] = c['updated_at'].isoformat()
    return JsonResponse(configs, safe=False)


@require_http_methods(["GET"])
@admin_required
def admin_get_system_config(request, config_id):
    """Obtener una configuración por ID"""
    try:
        config = SystemConfig.objects.get(id=config_id)
    except SystemConfig.DoesNotExist:
        return JsonResponse({'error': 'Configuración no encontrada'}, status=404)
    return JsonResponse(_config_to_dict(config))


@require_http_methods(["GET"])
@admin_required
def admin_get_system_config_by_key(request, key):
    """Obtener el valor de una configuración por su clave"""
    try:
        config = SystemConfig.objects.get(key=key)
    except SystemConfig.DoesNotExist:
        return JsonResponse({'error': 'Configuración no encontrada'}, status=404)
    return HttpResponse(config.value, content_type='text/plain')


@csrf_exempt
@require_http_methods(["POST"])
@admin_required
def admin_create_system_config(request):
    """Crear una nueva configuración"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not data.get('key'):
        return JsonResponse({'error': 'key es requerido'}, status=400)
    if data.get('value') is None:
        return JsonResponse({'error': 'value es requerido'}, status=400)

    key = data['key'].strip()
    if SystemConfig.objects.filter(key=key).exists():
        return JsonResponse({'error': 'La clave ya existe'}, status=409)

    config = SystemConfig.objects.create(
        key=key,
        value=data['value'],
        description=data.get('description', '').strip(),
    )
    return JsonResponse(_config_to_dict(config), status=201)


@csrf_exempt
@require_http_methods(["PUT", "PATCH"])
@admin_required
def admin_update_system_config(request, config_id):
    """Actualizar una configuración existente"""
    try:
        config = SystemConfig.objects.get(id=config_id)
    except SystemConfig.DoesNotExist:
        return JsonResponse({'error': 'Configuración no encontrada'}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not any(field in data for field in ('key', 'value', 'description')):
        return JsonResponse({'error': 'No hay campos para actualizar'}, status=400)

    if 'key' in data and data['key']:
        new_key = data['key'].strip()
        if new_key != config.key:
            if SystemConfig.objects.filter(key=new_key).exclude(id=config_id).exists():
                return JsonResponse({'error': 'La clave ya existe en otro registro'}, status=409)
            config.key = new_key

    if 'value' in data and data['value'] is not None:
        config.value = data['value']

    if 'description' in data:
        config.description = data['description'].strip()

    config.save()
    return JsonResponse(_config_to_dict(config))


@csrf_exempt
@require_http_methods(["DELETE"])
@admin_required
def admin_delete_system_config(request, config_id):
    """Eliminar una configuración"""
    try:
        config = SystemConfig.objects.get(id=config_id)
    except SystemConfig.DoesNotExist:
        return JsonResponse({'error': 'Configuración no encontrada'}, status=404)

    pk = config.pk
    config.delete()
    return JsonResponse({'message': 'Configuración eliminada correctamente', 'id': pk})


@csrf_exempt
@require_http_methods(["POST"])
@admin_required
def admin_bulk_update_system_configs(request):
    """Actualizar múltiples configuraciones en lote"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not isinstance(data, list) or len(data) == 0:
        return JsonResponse({'error': 'Se esperaba una lista de configuraciones no vacía'}, status=400)

    for i, item in enumerate(data):
        if not item.get('key'):
            return JsonResponse({'error': f'El item {i} no tiene key'}, status=400)
        if item.get('value') is None:
            return JsonResponse({'error': f'El item {i} no tiene value'}, status=400)

    updated_count = 0
    with transaction.atomic():
        for item in data:
            key = item['key'].strip()
            value = item['value']
            updated = SystemConfig.objects.filter(key=key).update(value=value)
            if updated:
                updated_count += updated
            elif item.get('create_if_not_exists', False):
                SystemConfig.objects.create(
                    key=key,
                    value=value,
                    description=item.get('description', ''),
                )
                updated_count += 1

    return JsonResponse({'message': 'Configuraciones actualizadas correctamente', 'updated_count': updated_count})


@require_http_methods(["GET"])
@admin_required
def admin_export_system_configs_csv(request):
    """Exportar configuraciones a CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="system_configs_export.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Clave', 'Valor', 'Descripción', 'Creada', 'Actualizada'])
    for config in SystemConfig.objects.all():
        writer.writerow([
            config.pk, config.key, config.value, config.description,
            config.created_at.isoformat(), config.updated_at.isoformat(),
        ])
    return response


@require_http_methods(["GET"])
@admin_required
def admin_get_system_configs_grouped(request):
    """Obtener configuraciones agrupadas por prefijo de clave"""
    grouped: dict = {}
    for config in SystemConfig.objects.all():
        prefix = config.key.split('.')[0] if '.' in config.key else 'general'
        grouped.setdefault(prefix, []).append({
            'id': config.pk,
            'key': config.key,
            'value': config.value,
            'description': config.description,
        })
    return JsonResponse(grouped)


@require_http_methods(["GET"])
@admin_required
def admin_get_system_configs_by_prefix(request, prefix):
    """Obtener configuraciones por prefijo de clave"""
    configs = list(SystemConfig.objects.filter(key__startswith=f"{prefix}."))
    return JsonResponse([_config_to_dict(c) for c in configs], safe=False)


# ===========================================================================
# Dashboard views
# ===========================================================================

@require_http_methods(["GET"])
@admin_required
def admin_dashboard(request):
    """Endpoint principal del dashboard de administración"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    limit = int(request.GET.get('limit', 10))
    if limit < 1 or limit > 50:
        limit = 10

    return JsonResponse({
        'totals': get_dashboard_totals(start_date, end_date),
        'top_tests': get_top_tests_lists(start_date, end_date, limit),
        'user_lists': get_user_lists(start_date, end_date, limit),
    })


def _parse_date(date_str, fmt='%Y-%m-%d'):
    try:
        return datetime.strptime(date_str, fmt).date()
    except (ValueError, TypeError):
        return None


def get_dashboard_totals(start_date=None, end_date=None):
    """Obtiene todos los totales del dashboard"""
    user_filters = Q()
    result_filters = Q()
    test_filters = Q()

    if start := _parse_date(start_date):
        user_filters &= Q(registered_at__date__gte=start)
        result_filters &= Q(started_at__date__gte=start)
        test_filters &= Q(created_at__date__gte=start)

    if end := _parse_date(end_date):
        user_filters &= Q(registered_at__date__lte=end)
        result_filters &= Q(started_at__date__lte=end)
        test_filters &= Q(created_at__date__lte=end)

    # Single aggregate for result statuses
    result_agg = Result.objects.filter(result_filters).aggregate(
        completed=Count('id', filter=Q(status='completed')),
        in_progress=Count('id', filter=Q(status='in_progress')),
        expired=Count('id', filter=Q(status='expired')),
    )

    # Single aggregate for test levels
    test_agg = Test.objects.filter(test_filters).aggregate(
        total=Count('id'),
        inactive=Count('id', filter=Q(is_active=False)),
        advanced=Count('id', filter=Q(level='Avanzado')),
        intermediate=Count('id', filter=Q(level='Intermedio')),
        beginner=Count('id', filter=Q(level='Principiante')),
    )

    active_users = (
        User.objects.filter(user_filters, results__status='completed')
        .annotate(test_count=Count('results'))
        .filter(test_count__gte=5)
        .distinct()
        .count()
    )

    return {
        'total_users': User.objects.filter(user_filters).count(),
        'active_users': active_users,
        'completed_tests': result_agg['completed'],
        'in_progress_tests': result_agg['in_progress'],
        'expired_tests': result_agg['expired'],
        'total_tests': test_agg['total'],
        'inactive_tests': test_agg['inactive'],
        'advanced_tests': test_agg['advanced'],
        'intermediate_tests': test_agg['intermediate'],
        'beginner_tests': test_agg['beginner'],
    }


def get_top_tests_lists(start_date=None, end_date=None, limit=10):
    """Obtiene las listas de tests – sin bucles N+1"""

    # Date filter for results joined through Test
    result_date_filter = Q()
    if start := _parse_date(start_date):
        result_date_filter &= Q(results__started_at__date__gte=start)
    if end := _parse_date(end_date):
        result_date_filter &= Q(results__started_at__date__lte=end)

    # Date filter for standalone Result querysets
    result_qs_filter = Q(status='completed')
    if start := _parse_date(start_date):
        result_qs_filter &= Q(started_at__date__gte=start)
    if end := _parse_date(end_date):
        result_qs_filter &= Q(started_at__date__lte=end)

    # -- Most completed --
    most_completed = (
        Test.objects.annotate(
            completed_count=Count('results', filter=Q(results__status='completed') & result_date_filter)
        ).order_by('-completed_count').values('id', 'title', 'completed_count')[:limit]
    )

    # -- Most in-progress --
    most_incomplete = (
        Test.objects.annotate(
            in_progress_count=Count('results', filter=Q(results__status='in_progress') & result_date_filter)
        ).order_by('-in_progress_count').values('id', 'title', 'in_progress_count')[:limit]
    )

    # -- Most expired --
    most_expired = (
        Test.objects.annotate(
            expired_count=Count('results', filter=Q(results__status='expired') & result_date_filter)
        ).order_by('-expired_count').values('id', 'title', 'expired_count')[:limit]
    )

    # -- Least started & oldest --
    least_started_oldest = (
        Test.objects.annotate(
            attempt_count=Count('results', filter=result_date_filter)
        ).order_by('attempt_count', 'created_at')
        .values('id', 'title', 'attempt_count', 'created_at')[:limit]
    )

    # -- Accuracy & time – single aggregate per test, no N+1 --
    completed_results_qs = Result.objects.filter(result_qs_filter)
    accuracy_time_agg = (
        completed_results_qs
        .values('test_id', 'test__title')
        .annotate(
            total_correct=Sum('correct_answers'),
            total_wrong=Sum('wrong_answers'),
            total_attempts=Count('id'),
            avg_time=Avg('time_taken'),
        )
    )

    accuracy_data = []
    time_data = []
    for item in accuracy_time_agg:
        total_q = (item['total_correct'] or 0) + (item['total_wrong'] or 0)
        acc = round((item['total_correct'] or 0) * 100 / total_q, 2) if total_q else 0.0
        avg_t = round(float(item['avg_time'] or 0), 2)
        base = {'id': item['test_id'], 'title': item['test__title'], 'total_attempts': item['total_attempts']}
        accuracy_data.append({**base, 'accuracy_rate': acc})
        time_data.append({**base, 'avg_time': avg_t})

    accuracy_data.sort(key=lambda x: x['accuracy_rate'], reverse=True)
    time_data.sort(key=lambda x: x['avg_time'], reverse=True)

    return {
        'most_completed': [
            {'id': t['id'], 'title': t['title'], 'count': t['completed_count']}
            for t in most_completed
        ],
        'most_incomplete': [
            {'id': t['id'], 'title': t['title'], 'count': t['in_progress_count']}
            for t in most_incomplete
        ],
        'most_expired': [
            {'id': t['id'], 'title': t['title'], 'count': t['expired_count']}
            for t in most_expired
        ],
        'least_started_oldest': [
            {'id': t['id'], 'title': t['title'], 'attempt_count': t['attempt_count'],
             'date': t['created_at'].isoformat()}
            for t in least_started_oldest
        ],
        'highest_accuracy': accuracy_data[:limit],
        'lowest_accuracy': sorted(accuracy_data, key=lambda x: x['accuracy_rate'])[:limit],
        'highest_avg_time': time_data[:limit],
        'lowest_avg_time': sorted(time_data, key=lambda x: x['avg_time'])[:limit],
    }


def get_user_lists(start_date=None, end_date=None, limit=10):
    """Obtiene las listas de usuarios"""
    user_filters = Q()
    if start := _parse_date(start_date):
        user_filters &= Q(registered_at__date__gte=start)
    if end := _parse_date(end_date):
        user_filters &= Q(registered_at__date__lte=end)

    new_users = (
        User.objects.filter(user_filters)
        .order_by('-registered_at')
        .values('id', 'username', 'role')[:limit]
    )

    most_active = (
        User.objects.annotate(
            completed_count=Count('results', filter=Q(results__status='completed'))
        ).filter(completed_count__gt=0)
        .order_by('-completed_count')
        .values('id', 'username', 'role', 'completed_count')[:limit]
    )

    least_active_oldest = (
        User.objects.annotate(
            completed_count=Count('results', filter=Q(results__status='completed'))
        ).filter(completed_count=0)
        .order_by('registered_at')
        .values('id', 'username', 'role', 'registered_at')[:limit]
    )

    recent_login = (
        User.objects.filter(login_at__isnull=False)
        .order_by('-login_at')
        .values('id', 'username', 'role', 'login_at')[:limit]
    )

    oldest_login = (
        User.objects.filter(login_at__isnull=False)
        .order_by('login_at')
        .values('id', 'username', 'role', 'login_at')[:limit]
    )

    return {
        'new_users_by_month': [
            {'id': u['id'], 'username': u['username'], 'role': u['role'], 'count': 1}
            for u in new_users
        ],
        'most_active_users': [
            {'id': u['id'], 'username': u['username'], 'role': u['role'], 'count': u['completed_count']}
            for u in most_active
        ],
        'least_active_oldest': [
            {'id': u['id'], 'username': u['username'], 'role': u['role'],
             'date': u['registered_at'].isoformat()}
            for u in least_active_oldest
        ],
        'recent_login': [
            {'id': u['id'], 'username': u['username'], 'role': u['role'],
             'date': u['login_at'].isoformat()}
            for u in recent_login
        ],
        'oldest_login': [
            {'id': u['id'], 'username': u['username'], 'role': u['role'],
             'date': u['login_at'].isoformat()}
            for u in oldest_login
        ],
    }


@require_http_methods(["GET"])
@admin_required
def get_test_detailed_stats(request, test_id):
    """Obtener estadísticas detalladas de un test específico"""
    try:
        test = Test.objects.get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'Test no encontrado'}, status=404)

    all_results = Result.objects.filter(test_id=test_id)
    agg = all_results.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        in_progress=Count('id', filter=Q(status='in_progress')),
        expired=Count('id', filter=Q(status='expired')),
        avg_correct=Avg('correct_answers', filter=Q(status='completed')),
        avg_wrong=Avg('wrong_answers', filter=Q(status='completed')),
        avg_time=Avg('time_taken', filter=Q(status='completed')),
    )

    avg_correct = agg['avg_correct'] or 0
    avg_wrong = agg['avg_wrong'] or 0
    total_avg = avg_correct + avg_wrong
    avg_accuracy = (avg_correct / total_avg * 100) if total_avg else 0

    total = agg['total'] or 0
    completed = agg['completed'] or 0
    completion_rate = (completed / total * 100) if total else 0

    return JsonResponse({
        'test_title': test.title,
        'difficulty_level': test.level,
        'topic_hierarchy': {
            'main_topic': test.main_topic,
            'sub_topic': test.sub_topic,
            'specific_topic': test.specific_topic,
        },
        'total_attempts': total,
        'completed_attempts': completed,
        'in_progress_attempts': agg['in_progress'] or 0,
        'expired_attempts': agg['expired'] or 0,
        'avg_accuracy': round(avg_accuracy, 2),
        'avg_time': round(agg['avg_time'] or 0, 2),
        'completion_rate': round(completion_rate, 2),
    })


@require_http_methods(["GET"])
@admin_required
def get_user_detailed_stats(request, user_id):
    """Obtener estadísticas detalladas de un usuario específico"""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Usuario no encontrado'}, status=404)

    agg = Result.objects.filter(user_id=user_id).aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        in_progress=Count('id', filter=Q(status='in_progress')),
        expired=Count('id', filter=Q(status='expired')),
        avg_correct=Avg('correct_answers', filter=Q(status='completed')),
        avg_wrong=Avg('wrong_answers', filter=Q(status='completed')),
        avg_time=Avg('time_taken', filter=Q(status='completed')),
    )

    avg_correct = agg['avg_correct'] or 0
    avg_wrong = agg['avg_wrong'] or 0
    total_avg = avg_correct + avg_wrong
    avg_accuracy = (avg_correct / total_avg * 100) if total_avg else 0

    completed_results = Result.objects.filter(user_id=user_id, status='completed')
    favorite_topic = (
        completed_results.values('test__main_topic')
        .annotate(count=Count('id'))
        .order_by('-count')
        .first()
    )
    favorite_level = (
        completed_results.values('test__level')
        .annotate(count=Count('id'))
        .order_by('-count')
        .first()
    )

    recent_activity = (
        Result.objects.filter(user_id=user_id)
        .select_related('test')
        .order_by('-started_at')[:10]
    )

    recent_list = []
    for result in recent_activity:
        total_ans = result.correct_answers + result.wrong_answers
        accuracy = (
            round(result.correct_answers / total_ans * 100, 2)
            if total_ans and result.status == 'completed' else 0
        )
        recent_list.append({
            'test_title': result.test.title,
            'status': result.status,
            'accuracy': accuracy,
            'time_taken': result.time_taken,
            'started_at': result.started_at.isoformat(),
        })

    return JsonResponse({
        'user_info': {
            'username': user.username,
            'email': user.email,
            'registered_at': user.registered_at.isoformat() if user.registered_at else None,
            'last_login': user.login_at.isoformat() if user.login_at else None,
            'role': user.role,
        },
        'test_stats': {
            'total_tests': agg['total'] or 0,
            'completed_tests': agg['completed'] or 0,
            'in_progress_tests': agg['in_progress'] or 0,
            'expired_tests': agg['expired'] or 0,
            'avg_accuracy': round(avg_accuracy, 2),
            'avg_time_per_test': round(agg['avg_time'] or 0, 2),
            'favorite_topic': favorite_topic['test__main_topic'] if favorite_topic else 'N/A',
            'favorite_level': favorite_level['test__level'] if favorite_level else 'N/A',
        },
        'recent_activity': recent_list,
    })


@require_http_methods(["GET"])
@admin_required
def get_dashboard_activity_summary(request):
    """Resumen de actividad de los últimos 30 días – sin bucle de queries"""
    end = timezone.now().date()
    start = end - timedelta(days=30)

    # ---- results: single query, aggregate in Python -------------------------
    results_qs = (
        Result.objects
        .filter(started_at__date__gte=start, started_at__date__lte=end)
        .values('started_at__date', 'status')
        .annotate(cnt=Count('id'))
    )
    results_by_day: dict = {}
    for row in results_qs:
        d = row['started_at__date'].isoformat()
        bucket = results_by_day.setdefault(d, {'total': 0, 'completed': 0, 'in_progress': 0, 'expired': 0})
        bucket['total'] += row['cnt']
        bucket[row['status']] = bucket.get(row['status'], 0) + row['cnt']

    # ---- new users: single query -------------------------------------------
    users_qs = (
        User.objects
        .filter(registered_at__date__gte=start, registered_at__date__lte=end)
        .values('registered_at__date')
        .annotate(cnt=Count('id'))
    )
    users_by_day = {row['registered_at__date'].isoformat(): row['cnt'] for row in users_qs}

    # ---- new tests: single query -------------------------------------------
    tests_qs = (
        Test.objects
        .filter(created_at__date__gte=start, created_at__date__lte=end)
        .values('created_at__date')
        .annotate(cnt=Count('id'))
    )
    tests_by_day = {row['created_at__date'].isoformat(): row['cnt'] for row in tests_qs}

    # ---- build day-by-day lists --------------------------------------------
    daily_results, daily_users, daily_tests = [], [], []
    current = start
    while current <= end:
        d = current.isoformat()
        bucket = results_by_day.get(d, {})
        daily_results.append({
            'date': d,
            'total': bucket.get('total', 0),
            'completed': bucket.get('completed', 0),
            'in_progress': bucket.get('in_progress', 0),
            'expired': bucket.get('expired', 0),
        })
        daily_users.append({'date': d, 'count': users_by_day.get(d, 0)})
        daily_tests.append({'date': d, 'count': tests_by_day.get(d, 0)})
        current += timedelta(days=1)

    return JsonResponse({
        'daily_results': daily_results,
        'daily_users': daily_users,
        'daily_tests': daily_tests,
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
    })


@require_http_methods(["GET"])
@admin_required
def get_dashboard_performance_metrics(request):
    """Métricas de rendimiento – todo en dos queries"""
    agg = Result.objects.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        total_correct=Sum('correct_answers', filter=Q(status='completed')),
        total_answers=Sum(
            F('correct_answers') + F('wrong_answers'),
            filter=Q(status='completed'),
        ),
        avg_time=Avg('time_taken', filter=Q(status='completed')),
    )

    total = agg['total'] or 0
    completed = agg['completed'] or 0
    completion_rate = (completed / total * 100) if total else 0

    total_answers = agg['total_answers'] or 0
    overall_accuracy = (
        (agg['total_correct'] or 0) / total_answers * 100 if total_answers else 0
    )

    level_distribution = list(Test.objects.values('level').annotate(count=Count('id')))
    role_distribution = list(User.objects.values('role').annotate(count=Count('id')))

    return JsonResponse({
        'completion_rate': round(completion_rate, 2),
        'overall_accuracy': round(overall_accuracy, 2),
        'average_time_minutes': round((agg['avg_time'] or 0) / 60, 2),
        'level_distribution': level_distribution,
        'role_distribution': role_distribution,
    })