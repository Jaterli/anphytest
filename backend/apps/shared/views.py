# shared/views.py
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from functools import wraps
import json
import logging

from apps.admin_panel.models import SystemConfig

from .models import (
    get_topics, get_main_topics, get_sub_topics, get_specific_topics,
    validate_and_suggest_topics, invalidate_topics_cache, get_topic_hierarchy,
    get_topic_statistics, insert_or_update_topic, get_predefined_levels
)

logger = logging.getLogger(__name__)

def admin_required(view_func):
    """Decorador para verificar que el usuario es administrador"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'user') or not request.user:
            return JsonResponse({'error': 'No autenticado'}, status=401)
        
        if request.user.role != 'admin':
            return JsonResponse({'error': 'Acceso denegado. Se requieren privilegios de administrador'}, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapper

@require_http_methods(["GET"])
def get_topics_view(request):
    """Obtiene la jerarquía completa de temas"""
    include_predefined = request.GET.get('include_predefined', 'true').lower() == 'true'
    force_refresh = request.GET.get('force_refresh', 'false').lower() == 'true'
    
    try:
        hierarchy = get_topics(include_predefined, force_refresh)
        return JsonResponse(hierarchy, safe=False)
    except Exception as e:
        logger.error(f"Error getting topics: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def get_main_topics_view(request):
    """Obtiene solo los temas principales"""
    try:
        topics = get_main_topics()
        return JsonResponse(topics, safe=False)
    except Exception as e:
        logger.error(f"Error getting main topics: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def get_sub_topics_view(request, main_topic):
    """Obtiene subtemas de un tema principal"""
    if not main_topic:
        return JsonResponse({'error': 'Main topic is required'}, status=400)
    
    try:
        sub_topics = get_sub_topics(main_topic)
        return JsonResponse(sub_topics, safe=False)
    except Exception as e:
        logger.error(f"Error getting sub topics for {main_topic}: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def get_specific_topics_view(request, main_topic, sub_topic):
    """Obtiene temas específicos"""
    if not main_topic or not sub_topic:
        return JsonResponse({'error': 'Both main_topic and sub_topic are required'}, status=400)
    
    try:
        specific_topics = get_specific_topics(main_topic, sub_topic)
        return JsonResponse(specific_topics, safe=False)
    except Exception as e:
        logger.error(f"Error getting specific topics for {main_topic}/{sub_topic}: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def validate_topic(request):
    """Valida una combinación de temas"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request body'}, status=400)
    
    main_topic = data.get('main_topic', '')
    sub_topic = data.get('sub_topic', '')
    specific_topic = data.get('specific_topic', '')
    
    if not main_topic or not sub_topic or not specific_topic:
        return JsonResponse({'error': 'main_topic, sub_topic and specific_topic are required'}, status=400)
    
    try:
        is_valid, suggestions = validate_and_suggest_topics(main_topic, sub_topic, specific_topic)
        return JsonResponse({
            'valid': is_valid,
            'suggestions': suggestions
        })
    except Exception as e:
        logger.error(f"Error validating topic: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["POST"])
@admin_required
def refresh_cache(request):
    """Refresca el cache de temas (admin only)"""
    try:
        invalidate_topics_cache()
        # Forzar recarga
        get_topics(True, True)
        return JsonResponse({'message': 'Topics cache refreshed successfully'})
    except Exception as e:
        logger.error(f"Error refreshing cache: {str(e)}")
        return JsonResponse({'error': 'Failed to refresh cache'}, status=500)

@require_http_methods(["GET"])
def get_topic_statistics_view(request):
    """Obtiene estadísticas de temas"""
    try:
        stats = get_topic_statistics()
        return JsonResponse(stats)
    except Exception as e:
        logger.error(f"Error getting topic statistics: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def get_topic_hierarchy_view(request):
    """Obtiene la estructura jerárquica completa"""
    try:
        hierarchy = get_topic_hierarchy()
        return JsonResponse(hierarchy, safe=False)
    except Exception as e:
        logger.error(f"Error getting topic hierarchy: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
@admin_required
def create_topic(request):
    """Crea un nuevo tema (admin only)"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request body'}, status=400)
    
    main_topic = data.get('main_topic', '').strip()
    sub_topic = data.get('sub_topic', '').strip()
    specific_topic = data.get('specific_topic', '').strip()
    is_predefined = data.get('is_predefined', False)
    
    if not main_topic or not sub_topic or not specific_topic:
        return JsonResponse({'error': 'main_topic, sub_topic and specific_topic are required'}, status=400)
    
    try:
        topic, created = insert_or_update_topic(main_topic, sub_topic, specific_topic, is_predefined)
        return JsonResponse({
            'message': 'Topic created successfully' if created else 'Topic updated successfully',
            'topic': {
                'main_topic': topic.main_topic,
                'sub_topic': topic.sub_topic,
                'specific_topic': topic.specific_topic,
                'is_predefined': topic.is_predefined
            }
        }, status=201 if created else 200)
    except Exception as e:
        logger.error(f"Error creating topic: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def get_predefined_levels_view(request):
    """Obtiene los niveles predefinidos"""
    levels = get_predefined_levels()
    return JsonResponse(levels, safe=False)


# ====== Configuraciones del Sistema ======

@require_http_methods(["GET"])
def get_system_config_by_key(request, key):
    """Obtiene el valor de una configuración por su clave (público, sin autenticación)"""
    
    try:
        system_config = SystemConfig.objects.get(key=key)
        # Devolver solo el valor como texto plano
        return HttpResponse(system_config.value, content_type='text/plain')
    except SystemConfig.DoesNotExist:
        return JsonResponse({'error': 'Configuración no encontrada'}, status=404)
    except Exception as e:
        logger.error(f"Error getting system config by key {key}: {str(e)}")
        return JsonResponse({'error': 'Error al obtener configuración'}, status=500)