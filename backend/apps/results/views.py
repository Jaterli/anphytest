# results/views.py
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.core.paginator import Paginator
from functools import wraps
import json
import logging
from django.db.models import Q, Sum, Count, Avg, F, Case, When, Value, FloatField, Prefetch, IntegerField
from django.db.models.functions import Coalesce, Round
from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.test.models import Test, Question, Answer
from apps.accounts.models import User
from .models import Result
from apps.shared.models import get_main_topics, get_predefined_levels, get_predefined_status

logger = logging.getLogger(__name__)

# Decorador para verificar autenticación
def login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'usuario no autenticado'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper

# Decorador para verificar admin
def admin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'No autenticado'}, status=401)
        
        if request.user.role != 'admin':
            logger.warning(f"Acceso denegado para usuario {request.user.id} con rol {request.user.role}")
            return JsonResponse({'error': 'Acceso denegado. Se requieren privilegios de administrador'}, status=403)
        
        logger.info(f"Acceso concedido para usuario {request.user.id} con rol {request.user.role}")
        return view_func(request, *args, **kwargs)
    return wrapper

# ====== Función auxiliar para obtener respuestas correctas de forma eficiente ======
def get_correct_answers_for_test(test_id):
    """Obtener todas las respuestas correctas de un test de una sola consulta"""
    cache_key = f'test_correct_answers_{test_id}'
    correct_answers = cache.get(cache_key)
    
    if correct_answers is None:
        answers = Answer.objects.filter(
            question__test_id=test_id,
            is_correct=True
        ).select_related('question').values('question_id', 'id', 'answer_text')
        
        correct_answers = {
            answer['question_id']: {'id': answer['id'], 'text': answer['answer_text']}
            for answer in answers
        }
        cache.set(cache_key, correct_answers, timeout=3600)  # Cache por 1 hora
    
    return correct_answers

# ====== Guardar o actualizar resultado ======
@csrf_exempt
@require_http_methods(["POST"])
@login_required
def save_or_update_result(request, test_id):
    """Guardar o actualizar resultado (progreso o finalización)"""
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    status = data.get('status')
    if status not in ['in_progress', 'completed', 'expired']:
        return JsonResponse({'error': 'status debe ser in_progress, completed o expired'}, status=400)
    
    # Verificar que el test existe
    try:
        test = Test.objects.only('id').get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    user_id = request.user.id
    answers = data.get('answers', {})
    time_taken = data.get('time_taken', 0)
    
    # Buscar resultado existente - usar select_for_update para evitar condiciones de carrera
    result = Result.objects.filter(
        user_id=user_id,
        test_id=test_id,
        status='in_progress'
    ).select_for_update().first()
    
    correct_count = 0
    wrong_count = 0
    
    # Calcular puntuación si está completado y hay respuestas
    if status == 'completed' and answers:
        correct_answers_map = get_correct_answers_for_test(test_id)
        
        for question_id, user_answer_id in answers.items():
            try:
                q_id = int(question_id)
                u_answer_id = int(user_answer_id)
                if correct_answers_map.get(q_id, {}).get('id') == u_answer_id:
                    correct_count += 1
                else:
                    wrong_count += 1
            except (ValueError, TypeError):
                wrong_count += 1
    
    if not result:
        # Crear nuevo resultado
        result = Result.objects.create(
            user_id=user_id,
            test_id=test_id,
            status=status,
            time_taken=time_taken,
            correct_answers=correct_count,
            wrong_answers=wrong_count,
            answers=answers
        )
    else:
        # Actualizar resultado existente
        result.status = status
        result.time_taken = time_taken
        result.updated_at = timezone.now()
        
        if status == 'completed':
            result.correct_answers = correct_count
            result.wrong_answers = wrong_count
        
        if answers:
            result.answers = answers
        
        result.save(update_fields=['status', 'time_taken', 'updated_at', 'correct_answers', 'wrong_answers', 'answers'])
    
    total_answers = len(answers)
    score_percentage = (correct_count / total_answers * 100) if total_answers > 0 else 0
    
    response = {
        'message': 'Resultado guardado exitosamente',
        'result_id': result.pk,
        'test_id': result.test_id,
        'status': result.status,
        'correct_answers': result.correct_answers,
        'wrong_answers': result.wrong_answers,
        'total': total_answers,
        'time_taken': result.time_taken,
        'score_percentage': round(score_percentage, 2)
    }
    
    return JsonResponse(response)

# ====== Obtener progreso actual de un test ======
@require_http_methods(["GET"])
@login_required
def get_test_progress(request, test_id):
    """Obtener progreso actual de un test"""
    
    user_id = request.user.id
    result = Result.objects.filter(
        user_id=user_id,
        test_id=test_id,
        status='in_progress'
    ).only('id', 'answers', 'time_taken', 'status').first()
    
    # Obtener test con preguntas y respuestas en una sola consulta
    try:
        test = Test.objects.prefetch_related(
            Prefetch('questions', queryset=Question.objects.prefetch_related('answers'))
        ).get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    if not result:
        return JsonResponse({
            'test': test_to_dict(test),
            'answers': {},
            'time_elapsed': 0,
            'progress': 0,
            'is_resuming': False
        })
    
    saved_answers = result.answers if isinstance(result.answers, dict) else (json.loads(result.answers) if result.answers else {})
    
    total_questions = test.questions.count()
    progress = (len(saved_answers) / total_questions * 100) if total_questions > 0 else 0
    
    return JsonResponse({
        'test': test_to_dict(test),
        'answers': saved_answers,
        'time_elapsed': result.time_taken,
        'progress': round(progress, 2),
        'is_resuming': True,
        'result_id': result.pk
    })

# ====== Obtener tests en progreso ======
@require_http_methods(["GET"])
@login_required
def get_my_in_progress_tests(request):
    """Obtener tests en progreso del usuario actual con filtros y paginación"""
    
    user_id = request.user.id
    
    # Obtener parámetros de consulta con valores por defecto seguros
    page = max(1, int(request.GET.get('page', 1)))
    page_size = min(50, max(1, int(request.GET.get('page_size', 10))))
    main_topic = request.GET.get('main_topic', '')
    level = request.GET.get('level', '')
    sort_by = request.GET.get('sort_by', 'result_updated_at')
    sort_order = request.GET.get('sort_order', 'desc')
    
    # Construir consulta base optimizada
    query = Result.objects.filter(
        user_id=user_id,
        status='in_progress'
    ).select_related('test')
    
    if main_topic:
        query = query.filter(test__main_topic=main_topic)
    if level:
        query = query.filter(test__level=level)
    
    total_tests = Result.objects.filter(user_id=user_id, status='in_progress').count()
    total_filtered_tests = query.count()
    
    # Mapeo de ordenación
    sort_mapping = {
        'result_updated_at': 'updated_at',
        'result_started_at': 'started_at',
        'result_time_taken': 'time_taken',
        'test_title': 'test__title',
        'test_created_at': 'test__created_at',
        'test_level': 'test__level',
    }
    order_field = sort_mapping.get(sort_by, 'updated_at')
    if sort_order == 'desc':
        order_field = f'-{order_field}'
    
    query = query.order_by(order_field)
    
    # Paginación
    paginator = Paginator(query, page_size)
    page_obj = paginator.get_page(page)
    
    # Procesar resultados eficientemente
    results_data = []
    total_progress = 0
    total_answered = 0
    total_time = 0
    
    for result in page_obj:
        answers = result.answers if isinstance(result.answers, dict) else (json.loads(result.answers) if result.answers else {})
        answered_count = len(answers)
        total_questions = result.test.questions.count()
        progress = (answered_count / total_questions * 100) if total_questions > 0 else 0
        
        total_progress += progress
        total_answered += answered_count
        total_time += result.time_taken
        
        results_data.append({
            'result_id': result.id,
            'user_id': result.user_id,
            'test_id': result.test.id,
            'time_taken': result.time_taken,
            'status': result.status,
            'answers': result.answers,
            'started_at': result.started_at.isoformat(),
            'updated_at': result.updated_at.isoformat(),
            'test_title': result.test.title,
            'test_description': result.test.description,
            'test_main_topic': result.test.main_topic,
            'test_sub_topic': result.test.sub_topic,
            'test_specific_topic': result.test.specific_topic,
            'test_level': result.test.level,
            'test_created_at': result.test.created_at.isoformat(),
            'total_questions': total_questions,
            'attempt': 1,
            'progress': round(progress, 2),
            'answered_count': answered_count,
            'remaining_count': total_questions - answered_count,
            'time_spent': format_time(result.time_taken)
        })
    
    # Ordenar por campos calculados si es necesario
    if sort_by == 'progress':
        results_data.sort(key=lambda x: x['progress'], reverse=(sort_order == 'desc'))
    elif sort_by == 'remaining_count':
        results_data.sort(key=lambda x: x['remaining_count'], reverse=(sort_order == 'desc'))
    
    # Estadísticas
    avg_progress = (total_progress / len(results_data)) if results_data else 0
    avg_time_per_test = (total_time // total_filtered_tests) if total_filtered_tests > 0 else 0
    
    # Obtener temas principales (optimizado con distinct)
    main_topics = Result.objects.filter(
        user_id=user_id,
        status='in_progress'
    ).exclude(test__main_topic='').values_list('test__main_topic', flat=True).distinct().order_by('test__main_topic')
    
    return JsonResponse({
        'data': {
            'results': results_data,
            'total_tests': total_tests,
            'total_pages': paginator.num_pages,
            'current_page': page,
            'page_size': page_size,
            'has_more': page < paginator.num_pages,
            'main_topics': list(main_topics)
        },
        'stats': {
            'total_filtered_tests': total_filtered_tests,
            'average_progress': round(avg_progress, 2),
            'total_questions_answered': total_answered,
            'total_time_spent': total_time,
            'avg_time_per_test': avg_time_per_test
        }
    })

# ====== Obtener tests completados ======
@require_http_methods(["GET"])
@login_required
def get_my_completed_tests(request):
    """Obtener tests completados del usuario actual con filtros y paginación"""
    
    user_id = request.user.id
    
    page = max(1, int(request.GET.get('page', 1)))
    page_size = min(50, max(1, int(request.GET.get('page_size', 10))))
    main_topic = request.GET.get('main_topic', '')
    level = request.GET.get('level', '')
    sort_by = request.GET.get('sort_by', 'result_updated_at')
    sort_order = request.GET.get('sort_order', 'desc')
    
    query = Result.objects.filter(
        user_id=user_id,
        status='completed',
        test__is_active=True
    ).select_related('test')
    
    if main_topic:
        query = query.filter(test__main_topic=main_topic)
    if level:
        query = query.filter(test__level=level)
    
    total_tests = Result.objects.filter(user_id=user_id, status='completed').count()
    total_filtered_tests = query.count()
    
    # Mapeo de ordenación
    sort_mapping = {
        'result_updated_at': 'updated_at',
        'result_started_at': 'started_at',
        'result_time_taken': 'time_taken',
        'test_title': 'test__title',
        'test_created_at': 'test__created_at',
        'test_level': 'test__level',
    }
    order_field = sort_mapping.get(sort_by, 'updated_at')
    
    if sort_by != 'score' and order_field:
        if sort_order == 'desc':
            order_field = f'-{order_field}'
        query = query.order_by(order_field)
    else:
        query = query.order_by('-updated_at')
    
    paginator = Paginator(query, page_size)
    page_obj = paginator.get_page(page)
    
    results_data = []
    total_questions_sum = 0
    total_correct_sum = 0
    total_time_sum = 0
    
    for result in page_obj:
        total_questions = result.test.questions.count()
        score_percent = (result.correct_answers / total_questions * 100) if total_questions > 0 else 0
        total_answered = result.correct_answers + result.wrong_answers
        accuracy = (result.correct_answers / total_answered * 100) if total_answered > 0 else 0
        
        total_questions_sum += total_questions
        total_correct_sum += result.correct_answers
        total_time_sum += result.time_taken
        
        results_data.append({
            'result_id': result.id,
            'user_id': result.user_id,
            'test_id': result.test.id,
            'correct_answers': result.correct_answers,
            'wrong_answers': result.wrong_answers,
            'time_taken': result.time_taken,
            'status': result.status,
            'started_at': result.started_at.isoformat(),
            'updated_at': result.updated_at.isoformat(),
            'test_title': result.test.title,
            'test_description': result.test.description,
            'test_main_topic': result.test.main_topic,
            'test_sub_topic': result.test.sub_topic,
            'test_specific_topic': result.test.specific_topic,
            'test_level': result.test.level,
            'test_created_at': result.test.created_at.isoformat(),
            'total_questions': total_questions,
            'attempt': 1,
            'score_percent': round(score_percent, 2),
            'score_rounded': int(round(score_percent)),
            'accuracy': round(accuracy, 2)
        })
    
    if sort_by == 'score':
        results_data.sort(key=lambda x: x['score_percent'], reverse=(sort_order == 'desc'))
    
    avg_score = (total_correct_sum / total_questions_sum * 100) if total_questions_sum > 0 else 0
    
    main_topics = Result.objects.filter(
        user_id=user_id,
        status='completed'
    ).exclude(test__main_topic='').values_list('test__main_topic', flat=True).distinct().order_by('test__main_topic')
    
    return JsonResponse({
        'data': {
            'test_results': results_data,
            'total_tests': total_tests,
            'total_pages': paginator.num_pages,
            'current_page': page,
            'page_size': page_size,
            'has_more': page < paginator.num_pages,
            'main_topics': list(main_topics)
        },
        'stats': {
            'average_score': round(avg_score, 2),
            'total_time_spent': total_time_sum,
            'total_filtered_tests': total_filtered_tests,
            'total_questions_answered': total_correct_sum
        }
    })

# ====== Eliminar progreso de un test ======
@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def delete_test_progress(request, test_id):
    """Eliminar progreso de un test"""
    
    deleted_count, _ = Result.objects.filter(
        user_id=request.user.id,
        test_id=test_id,
        status='in_progress'
    ).delete()
    
    return JsonResponse({'message': 'progreso eliminado' if deleted_count > 0 else 'no se encontró progreso para eliminar'})

# ====== Obtener respuestas incorrectas ======
@require_http_methods(["GET"])
@login_required
def get_incorrect_answers(request, result_id):
    """Obtener respuestas incorrectas de un resultado completado"""
    
    try:
        result = Result.objects.select_related('test').get(id=result_id, user_id=request.user.id)
    except Result.DoesNotExist:
        return JsonResponse({'error': 'resultado no encontrado'}, status=404)
    
    # Parsear respuestas del usuario
    user_answers = result.answers if isinstance(result.answers, dict) else (json.loads(result.answers) if result.answers else {})
    
    # Obtener respuestas correctas del test (usando caché)
    correct_answers_map = get_correct_answers_for_test(result.test_id)
    
    # Obtener preguntas con sus respuestas
    questions = Question.objects.filter(test_id=result.test_id).prefetch_related('answers')
    
    incorrect_questions = []
    for idx, question in enumerate(questions, 1):
        user_answer_id = user_answers.get(str(question.pk))
        correct_answer = correct_answers_map.get(question.pk)
        
        if user_answer_id != correct_answer['id'] if correct_answer else True:
            # Obtener texto de respuesta del usuario
            user_answer_text = 'No respondida'
            if user_answer_id:
                user_answer = Answer.objects.filter(id=user_answer_id).values_list('answer_text', flat=True).first()
                if user_answer:
                    user_answer_text = user_answer
            
            incorrect_questions.append({
                'question_id': question.pk,
                'question_number': idx,
                'question_text': question.question_text,
                'correct_answer_id': correct_answer['id'] if correct_answer else None,
                'correct_answer_text': correct_answer['text'] if correct_answer else 'No definida',
                'user_answer_text': user_answer_text
            })
    
    total_questions = result.correct_answers + result.wrong_answers
    score_percentage = (result.correct_answers / total_questions * 100) if total_questions > 0 else 0
    
    return JsonResponse({
        'incorrect_questions': incorrect_questions,
        'summary': {
            'total_questions': total_questions,
            'total_correct': result.correct_answers,
            'total_incorrect': result.wrong_answers,
            'questions_with_errors': len(incorrect_questions),
            'score_percentage': round(score_percentage, 2)
        }
    })

# ====== Función auxiliar ======
def test_to_dict(test):
    """Convierte un objeto Test a diccionario con todas sus relaciones"""
    return {
        'id': test.id,
        'title': test.title,
        'description': test.description,
        'main_topic': test.main_topic,
        'sub_topic': test.sub_topic,
        'specific_topic': test.specific_topic,
        'level': test.level,
        'is_active': test.is_active,
        'created_by': test.created_by,
        'created_at': test.created_at.isoformat() if test.created_at else None,
        'updated_at': test.updated_at.isoformat() if test.updated_at else None,
        'questions': [
            {
                'id': q.id,
                'question_text': q.question_text,
                'answers': [
                    {
                        'id': a.id,
                        'answer_text': a.answer_text,
                        'is_correct': a.is_correct
                    }
                    for a in q.answers.all()
                ]
            }
            for q in test.questions.all()
        ]
    }

def format_time(seconds):
    """Formatea segundos a formato legible"""
    if seconds <= 0:
        return ''
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

# ====== Vistas de Resultados (Admin) ======

@require_http_methods(["GET"])
@admin_required
def get_result_stats(request):
    """Obtener estadísticas generales de resultados"""
    
    # Usar caché para estadísticas que no cambian frecuentemente
    cache_key = 'result_stats'
    stats_data = cache.get(cache_key)
    
    if stats_data is None:
        total_results = Result.objects.count()
        
        status_stats = list(Result.objects.values('status').annotate(count=Count('id')))
        
        # Estadísticas de completados
        completed_results = Result.objects.filter(status='completed')
        total_correct = completed_results.aggregate(total=Sum('correct_answers'))['total'] or 0
        total_answered = completed_results.aggregate(
            total=Sum(F('correct_answers') + F('wrong_answers'))
        )['total'] or 0
        avg_score = (total_correct / total_answered * 100) if total_answered > 0 else 0
        
        # Resultados por día (últimos 30 días)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        daily_stats = Result.objects.filter(
            started_at__gte=thirty_days_ago
        ).extra(
            {'day': "DATE(started_at)"}
        ).values('day').annotate(
            count=Count('id'),
            avg_score=Avg(
                Case(
                    When(status='completed', then=F('correct_answers') * 100.0 / (F('correct_answers') + F('wrong_answers'))),
                    default=Value(0.0),
                    output_field=FloatField()
                )
            )
        ).order_by('day')
        
        # Resultados por nivel de test
        level_stats = list(Result.objects.filter(status='completed').select_related('test').values('test__level').annotate(
            count=Count('id'),
            avg_score=Avg(F('correct_answers') * 100.0 / (F('correct_answers') + F('wrong_answers')))
        ))
        
        # Top 10 tests más realizados
        top_tests = list(Result.objects.select_related('test').values(
            'test__id', 'test__title'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:10])
        
        # Top 10 usuarios con más resultados
        top_users = list(Result.objects.select_related('user').values(
            'user__id', 'user__username', 'user__email'
        ).annotate(
            count=Count('id'),
            avg_score=Avg(
                Case(
                    When(status='completed', then=F('correct_answers') * 100.0 / (F('correct_answers') + F('wrong_answers'))),
                    default=Value(0.0),
                    output_field=FloatField()
                )
            )
        ).order_by('-count')[:10])
        
        stats_data = {
            'stats': {
                'total_results': total_results,
                'average_score': round(avg_score, 2),
                'by_status': status_stats,
                'by_level': level_stats,
                'daily_last_30_days': [
                    {
                        'date': item['day'].isoformat() if item['day'] else None,
                        'count': item['count'],
                        'avg_score': round(float(item['avg_score']), 2) if item['avg_score'] else 0
                    }
                    for item in daily_stats
                ],
                'top_tests': [
                    {
                        'test_id': item['test__id'],
                        'test_title': item['test__title'],
                        'times_taken': item['count']
                    }
                    for item in top_tests
                ],
                'top_users': [
                    {
                        'user_id': item['user__id'],
                        'username': item['user__username'],
                        'email': item['user__email'],
                        'results_count': item['count'],
                        'avg_score': round(float(item['avg_score']), 2) if item['avg_score'] else 0
                    }
                    for item in top_users
                ]
            },
            'timestamp': timezone.now().isoformat()
        }
        
        cache.set(cache_key, stats_data, timeout=300)  # Cache por 5 minutos
    
    return JsonResponse(stats_data)

@require_http_methods(["GET"])
@admin_required
def get_result_detail(request, result_id):
    """Obtener detalle completo de un resultado"""
    try:
        result = Result.objects.select_related('user', 'test').get(id=result_id)
    except Result.DoesNotExist:
        return JsonResponse({'error': 'Resultado no encontrado'}, status=404)
    
    total_answered = result.correct_answers + result.wrong_answers
    score = round((result.correct_answers * 100.0 / total_answered), 2) if result.status == 'completed' and total_answered > 0 else 0
    
    answers_data = result.answers if isinstance(result.answers, dict) else (json.loads(result.answers) if result.answers else None)
    
    return JsonResponse({
        'id': result.pk,
        'user_id': result.user_id,
        'test_id': result.test_id,
        'correct_answers': result.correct_answers,
        'wrong_answers': result.wrong_answers,
        'total_questions': total_answered,
        'score': score,
        'time_taken': result.time_taken,
        'status': result.status,
        'answers': answers_data,
        'started_at': result.started_at.isoformat() if result.started_at else None,
        'updated_at': result.updated_at.isoformat() if result.updated_at else None,
        'user': {
            'id': result.user.id,
            'username': result.user.username,
            'email': result.user.email,
            'first_name': result.user.first_name,
            'last_name': result.user.last_name,
            'role': result.user.role,
        },
        'test': {
            'id': result.test.id,
            'title': result.test.title,
            'description': result.test.description,
            'main_topic': result.test.main_topic,
            'sub_topic': result.test.sub_topic,
            'specific_topic': result.test.specific_topic,
            'level': result.test.level,
            'total_questions': result.test.questions.count(),
        }
    })

@require_http_methods(["GET"])
@admin_required
def export_results_csv(request):
    """Exportar resultados a CSV"""
    import csv
    
    results = Result.objects.select_related('user', 'test').iterator(chunk_size=1000)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="results_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Usuario', 'Email', 'Test', 'Nivel', 'Tema Principal',
        'Subtema', 'Correctas', 'Incorrectas', 'Total', 'Puntuación (%)',
        'Tiempo (seg)', 'Estado', 'Fecha Inicio', 'Última Actualización'
    ])
    
    for result in results:
        writer.writerow([
            result.pk,
            result.user.username,
            result.user.email,
            result.test.title,
            result.test.level,
            result.test.main_topic,
            result.test.sub_topic,
            result.correct_answers,
            result.wrong_answers,
            result.correct_answers + result.wrong_answers,
            result.score_percentage,
            result.time_taken,
            result.status,
            result.started_at.isoformat() if result.started_at else '',
            result.updated_at.isoformat() if result.updated_at else '',
        ])
    
    return response

# ====== Admin: Obtener lista de resultados con filtros avanzados ======
@require_http_methods(["GET"])
@admin_required
def get_results_list(request):
    """Obtener lista de resultados con paginación, filtrado y ordenación"""
    
    page = max(1, int(request.GET.get('page', 1)))
    page_size = min(100, max(1, int(request.GET.get('page_size', 20))))
    sort_by = request.GET.get('sort_by', 'updated_at')
    sort_order = request.GET.get('sort_order', 'desc')
    
    # Construir query base
    results_query = Result.objects.select_related('user', 'test').annotate(
        score=Case(
            When(status='completed', then=Coalesce(
                Round(F('correct_answers') * 100.0 / (F('correct_answers') + F('wrong_answers')), 2),
                Value(0.0)
            )),
            default=Value(0.0),
            output_field=FloatField()
        ),
        total_questions=F('correct_answers') + F('wrong_answers')
    )
    
    # Aplicar filtros
    filters = {}
    
    # Filtros de usuario
    if user_id := request.GET.get('user_id'):
        try:
            filters['user_id'] = int(user_id)
        except ValueError:
            pass
    
    if user_role := request.GET.get('user_role'):
        filters['user__role'] = user_role
    
    if user_email := request.GET.get('user_email'):
        results_query = results_query.filter(user__email__icontains=user_email)
    
    if user_username := request.GET.get('user_username'):
        results_query = results_query.filter(user__username__icontains=user_username)
    
    # Filtros de test
    if test_id := request.GET.get('test_id'):
        try:
            filters['test_id'] = int(test_id)
        except ValueError:
            pass
    
    if test_title := request.GET.get('test_title'):
        results_query = results_query.filter(test__title__icontains=test_title)
    
    if test_main_topic := request.GET.get('test_main_topic'):
        filters['test__main_topic'] = test_main_topic
    
    if test_sub_topic := request.GET.get('test_sub_topic'):
        filters['test__sub_topic'] = test_sub_topic
    
    if test_specific_topic := request.GET.get('test_specific_topic'):
        filters['test__specific_topic'] = test_specific_topic
    
    if test_level := request.GET.get('test_level'):
        filters['test__level'] = test_level
    
    if test_created_by := request.GET.get('test_created_by'):
        try:
            filters['test__created_by'] = int(test_created_by)
        except ValueError:
            pass
    
    # Filtros de resultado
    if status := request.GET.get('status'):
        filters['status'] = status
    
    # Aplicar filtros de diccionario
    results_query = results_query.filter(**filters)
    
    # Filtros de puntuación
    if min_score := request.GET.get('min_score'):
        try:
            results_query = results_query.filter(score__gte=float(min_score))
        except ValueError:
            pass
    
    if max_score := request.GET.get('max_score'):
        try:
            results_query = results_query.filter(score__lte=float(max_score))
        except ValueError:
            pass
    
    # Filtros de fecha
    if start_date := request.GET.get('start_date'):
        try:
            results_query = results_query.filter(started_at__date__gte=datetime.strptime(start_date, '%Y-%m-%d').date())
        except ValueError:
            pass
    
    if end_date := request.GET.get('end_date'):
        try:
            results_query = results_query.filter(started_at__date__lte=datetime.strptime(end_date, '%Y-%m-%d').date())
        except ValueError:
            pass
    
    # Búsqueda general
    if search := request.GET.get('search'):
        results_query = results_query.filter(
            Q(user__username__icontains=search) |
            Q(user__email__icontains=search) |
            Q(test__title__icontains=search) |
            Q(test__main_topic__icontains=search) |
            Q(test__sub_topic__icontains=search)
        )
    
    total_results = Result.objects.count()
    total_filtered_results = results_query.count()
    
    # Aplicar ordenación
    valid_sort_fields = ['id', 'started_at', 'updated_at', 'time_taken', 'correct_answers', 'score']
    if sort_by not in valid_sort_fields:
        sort_by = 'updated_at'
    
    order_field = f'-{sort_by}' if sort_order == 'desc' else sort_by
    results_query = results_query.order_by(order_field)
    
    # Paginación
    offset = (page - 1) * page_size
    paginated_results = results_query[offset:offset + page_size]
    
    # Convertir a lista de diccionarios manualmente
    results_list = []
    for result in paginated_results:
        results_list.append({
            'id': result.pk,
            'user_id': result.user_id,
            'test_id': result.test_id,
            'correct_answers': result.correct_answers,
            'wrong_answers': result.wrong_answers,
            'total_questions': result.total_questions,
            'score': result.score,
            'time_taken': result.time_taken,
            'status': result.status,
            'answers': result.answers,
            'started_at': result.started_at.isoformat(),
            'updated_at': result.updated_at.isoformat(),
            'user_username': result.user.username,
            'user_email': result.user.email,
            'user_first_name': result.user.first_name,
            'user_last_name': result.user.last_name,
            'user_role': result.user.role,
            'test_title': result.test.title,
            'test_description': result.test.description,
            'test_main_topic': result.test.main_topic,
            'test_sub_topic': result.test.sub_topic,
            'test_specific_topic': result.test.specific_topic,
            'test_level': result.test.level,
        })
    
    return JsonResponse({
        'results': results_list,
        'filters_applied': request.GET.dict(),
        'available_filters': {
            'main_topics': get_main_topics(),
            'levels': get_predefined_levels(),
            'statuses': get_predefined_status(),
            'roles': ['user', 'admin'],
        },
        'stats': {
            'total_results': total_results,
            'total_filtered_results': total_filtered_results,
        }
    })


# ====== Eliminar un resultado específico ======
@csrf_exempt
@require_http_methods(["DELETE"])
@admin_required
def delete_result(request, result_id):
    """Eliminar un resultado específico"""
    deleted, _ = Result.objects.filter(id=result_id).delete()
    if not deleted:
        return JsonResponse({'error': 'Resultado no encontrado'}, status=404)
    
    # Limpiar caché de estadísticas
    cache.delete('result_stats')
    
    return JsonResponse({'message': 'Resultado eliminado', 'id': result_id})

# ====== Eliminar múltiples resultados (Bulk Delete) ======
@csrf_exempt
@require_http_methods(["DELETE"])
@admin_required
def delete_results_bulk(request):
    """Eliminar múltiples resultados"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return JsonResponse({'error': 'Se requiere una lista de IDs'}, status=400)
    
    try:
        ids = [int(id_val) for id_val in ids]
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Los IDs deben ser números enteros'}, status=400)
    
    deleted_count, _ = Result.objects.filter(id__in=ids).delete()
    
    # Limpiar caché de estadísticas
    cache.delete('result_stats')
    
    return JsonResponse({
        'message': f'{deleted_count} resultados eliminados',
        'deleted_count': deleted_count
    })

# ====== Resultados de Usuario (Admin) ======
@require_http_methods(["GET"])
@admin_required
def get_user_results(request, user_id):
    """Obtener resultados de tests de un usuario específico"""
    
    try:
        user = User.objects.only('id', 'username', 'email', 'first_name', 'last_name', 'role', 'registered_at').get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'usuario no encontrado'}, status=404)
    
    # Obtener parámetros de consulta
    page = max(1, int(request.GET.get('page', 1)))
    page_size = min(100, max(1, int(request.GET.get('page_size', 20))))
    status_filter = request.GET.get('status', '')
    sort_by = request.GET.get('sort_by', 'updated_at')
    sort_order = request.GET.get('sort_order', 'desc')
    search = request.GET.get('search', '')
    level = request.GET.get('level', '')
    main_topic = request.GET.get('main_topic', '')
    sub_topic = request.GET.get('sub_topic', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    
    # ===== CONTAR TOTAL DE RESULTADOS (sin filtros) =====
    total_results = Result.objects.filter(user_id=user_id).count()
    
    # ===== CONSTRUIR CONSULTA BASE CON FILTROS =====
    query = Result.objects.filter(user_id=user_id).select_related('test')
    
    # Aplicar filtros
    if status_filter and status_filter != 'all':
        query = query.filter(status=status_filter)
    
    if level:
        query = query.filter(test__level=level)
    
    if main_topic:
        query = query.filter(test__main_topic=main_topic)
    
    if sub_topic:
        query = query.filter(test__sub_topic=sub_topic)
    
    if search:
        query = query.filter(
            Q(test__title__icontains=search) |
            Q(test__description__icontains=search)
        )
    
    if from_date:
        try:
            from_date_parsed = datetime.strptime(from_date, '%Y-%m-%d').date()
            query = query.filter(started_at__date__gte=from_date_parsed)
        except ValueError:
            pass
    
    if to_date:
        try:
            to_date_parsed = datetime.strptime(to_date, '%Y-%m-%d').date()
            next_day = to_date_parsed + timedelta(days=1)
            query = query.filter(started_at__date__lt=next_day)
        except ValueError:
            pass
    
    # ===== CONTAR RESULTADOS FILTRADOS =====
    total_filtered_results = query.count()
    
    # ===== APLICAR ORDENACIÓN =====
    sort_mapping = {
        'average_score': 'score_percentage',
        'title': 'test__title',
        'level': 'test__level',
        't_created_at': 'test__created_at',
        'time_taken': 'time_taken',
        'started_at': 'started_at',
        'updated_at': 'updated_at',
    }
    
    order_field = sort_mapping.get(sort_by, 'updated_at')
    
    if sort_by == 'average_score':
        # Ordenar por score_percentage (propiedad calculada)
        results_list = list(query)
        results_list.sort(
            key=lambda x: x.score_percentage if x.status == 'completed' else 0,
            reverse=(sort_order == 'desc')
        )
        # Paginación manual
        offset = (page - 1) * page_size
        paginated_results = results_list[offset:offset + page_size]
        total_pages = (len(results_list) + page_size - 1) // page_size if page_size > 0 else 1
    else:
        # Ordenación normal
        if sort_order == 'desc':
            order_field = f'-{order_field}'
        query = query.order_by(order_field)
        
        # Paginación
        paginator = Paginator(query, page_size)
        page_obj = paginator.get_page(page)
        paginated_results = page_obj.object_list
        total_pages = paginator.num_pages
    
    # ===== PROCESAR RESULTADOS =====
    user_results = []
    for result in paginated_results:
        total_questions = result.test.questions.count()
        
        # Calcular score
        score = 0.0
        if total_questions > 0 and result.status == 'completed':
            score = (result.correct_answers / total_questions * 100)
            score = round(score * 10) / 10  # Redondear a 1 decimal
        
        # Calcular answered_count
        answered_count = 0
        if result.status == 'completed':
            answered_count = result.correct_answers + result.wrong_answers
        elif result.status == 'in_progress' and result.answers:
            answers = result.answers if isinstance(result.answers, dict) else (json.loads(result.answers) if result.answers else {})
            answered_count = len(answers)
        
        user_results.append({
            'id': result.pk,
            'test_id': result.test.id,
            'test_title': result.test.title,
            'test_description': result.test.description,
            'test_main_topic': result.test.main_topic,
            'test_sub_topic': result.test.sub_topic,
            'test_specific_topic': result.test.specific_topic,
            'test_level': result.test.level,
            'total_questions': total_questions,
            'correct_answers': result.correct_answers,
            'wrong_answers': result.wrong_answers,
            'score': score,
            'time_taken': result.time_taken,
            'status': result.status,
            'started_at': result.started_at.isoformat(),
            'updated_at': result.updated_at.isoformat(),
            'test_created_at': result.test.created_at.isoformat(),
            'answered_count': answered_count
        })
    
    # ===== OBTENER ESTADÍSTICAS DETALLADAS =====
    # Construir query de estadísticas con los mismos filtros
    stats_query = Result.objects.filter(user_id=user_id)
    
    if status_filter and status_filter != 'all':
        stats_query = stats_query.filter(status=status_filter)
    
    if from_date:
        try:
            from_date_parsed = datetime.strptime(from_date, '%Y-%m-%d').date()
            stats_query = stats_query.filter(started_at__date__gte=from_date_parsed)
        except ValueError:
            pass
    
    if to_date:
        try:
            to_date_parsed = datetime.strptime(to_date, '%Y-%m-%d').date()
            next_day = to_date_parsed + timedelta(days=1)
            stats_query = stats_query.filter(started_at__date__lt=next_day)
        except ValueError:
            pass
    
    stats = stats_query.aggregate(
        completed_tests=Count('id', filter=Q(status='completed')),
        in_progress_tests=Count('id', filter=Q(status='in_progress')),
        total_time_spent=Coalesce(Sum('time_taken'), Value(0)),
        total_questions_answered=Coalesce(
            Sum(
                Case(
                    When(status='completed', then=F('correct_answers') + F('wrong_answers')),
                    default=Value(0),
                    output_field=IntegerField()
                )
            ),
            Value(0)
        ),
        total_correct_answers=Coalesce(
            Sum(
                Case(
                    When(status='completed', then=F('correct_answers')),
                    default=Value(0),
                    output_field=IntegerField()
                )
            ),
            Value(0)
        )
    )
    
    # Calcular promedio de score
    avg_score = 0.0
    if stats['completed_tests'] > 0 and stats['total_questions_answered'] > 0:
        avg_score = (stats['total_correct_answers'] / stats['total_questions_answered'] * 100)
        avg_score = round(avg_score * 10) / 10
    
    # Obtener temas disponibles para filtros
    main_topics = list(
        Result.objects.filter(user_id=user_id)
        .exclude(test__main_topic='')
        .values_list('test__main_topic', flat=True)
        .distinct()
        .order_by('test__main_topic')
    )
    
    # ===== CONSTRUIR RESPUESTA =====
    response = {
        'user': {
            'id': user.pk,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'registered_at': user.registered_at.isoformat() if user.registered_at else None,
        },
        'results': user_results,
        'filters_applied': {
            'page': page,
            'page_size': page_size,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'status': status_filter,
            'level': level,
            'main_topic': main_topic,
            'sub_topic': sub_topic,
            'from_date': from_date,
            'to_date': to_date,
            'search': search,
        },
        'available_filters': {
            'main_topics': main_topics,
            'levels': get_predefined_levels(),
            'statuses': ['all', 'completed', 'in_progress'],
        },
        'stats': {
            'total_results': total_results,
            'total_filtered_results': total_filtered_results,
            'completed_tests': stats['completed_tests'] or 0,
            'in_progress_tests': stats['in_progress_tests'] or 0,
            'average_score': avg_score,
            'total_time_spent': stats['total_time_spent'] or 0,
            'total_questions_answered': stats['total_questions_answered'] or 0,
            'total_correct_answers': stats['total_correct_answers'] or 0,
        }
    }
    
    # Si se ordenó por average_score, añadir paginación manual
    if sort_by == 'average_score':
        total_pages = (len(results_list) + page_size - 1) // page_size if page_size > 0 else 1
        response['pagination'] = {
            'current_page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'total_items': len(results_list)
        }
    
    return JsonResponse(response)


@require_http_methods(["GET"])
@admin_required
def get_user_result_details(request, result_id, user_id=None):
    """Obtener detalles específicos de un resultado"""
    
    target_user_id = user_id if user_id else request.user.id
    
    if user_id and request.user.id != int(user_id) and request.user.role != 'admin':
        return JsonResponse({'error': 'no autorizado'}, status=403)
    
    try:
        user = User.objects.only('id', 'username', 'email', 'first_name', 'last_name', 'role', 'registered_at').get(id=target_user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'usuario no encontrado'}, status=404)
    
    try:
        result = Result.objects.select_related('test').get(
            id=result_id,
            user_id=target_user_id
        )
    except Result.DoesNotExist:
        return JsonResponse({'error': 'resultado no encontrado'}, status=404)
    
    # Parsear respuestas del usuario
    user_answers = result.answers if isinstance(result.answers, dict) else (json.loads(result.answers) if result.answers else {})
    
    # Obtener preguntas con respuestas
    questions = Question.objects.filter(test_id=result.test_id).prefetch_related('answers')
    
    question_details = []
    for idx, question in enumerate(questions, 1):
        answers_detail = []
        user_selected_answer = user_answers.get(str(question.pk))
        
        for answer in question.answers.all():
            answers_detail.append({
                'id': answer.pk,
                'answer_text': answer.answer_text,
                'is_correct': answer.is_correct,
                'is_selected': user_selected_answer == answer.pk
            })
        
        is_correct = user_selected_answer and any(
            a.pk == user_selected_answer and a.is_correct 
            for a in question.answers.all()
        )
        
        question_details.append({
            'id': question.pk,
            'question_number': idx,
            'question_text': question.question_text,
            'answers': answers_detail,
            'user_answer_id': user_selected_answer,
            'is_correct_answered': is_correct if user_selected_answer else None
        })
    
    total_questions = len(question_details)
    score_percentage = round((result.correct_answers / total_questions * 100), 1) if total_questions > 0 and result.status == 'completed' else 0
    
    return JsonResponse({
        'result': {
            'id': result.pk,
            'user_id': result.user_id,
            'test_id': result.test_id,
            'correct_answers': result.correct_answers,
            'wrong_answers': result.wrong_answers,
            'time_taken': result.time_taken,
            'time_formatted': format_time(result.time_taken),
            'avg_time_per_question': round(result.time_taken / total_questions, 1) if total_questions > 0 and result.status == 'completed' else 0,
            'status': result.status,
            'answered_questions': user_answers,
            'answered_count': len(user_answers),
            'started_at': result.started_at.isoformat(),
            'updated_at': result.updated_at.isoformat(),
        },
        'user': {
            'id': user.pk,
            'username': user.username,
            'role': user.role,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'registered_at': user.registered_at.isoformat() if user.registered_at else None,
        },
        'test': {
            'id': result.test.id,
            'title': result.test.title,
            'description': result.test.description,
            'main_topic': result.test.main_topic,
            'sub_topic': result.test.sub_topic,
            'specific_topic': result.test.specific_topic,
            'level': result.test.level,
            'created_at': result.test.created_at.isoformat(),
            'total_questions': total_questions,
        },
        'questions': question_details,
        'total_questions': total_questions,
        'score_details': {
            'correct': result.correct_answers,
            'wrong': result.wrong_answers,
            'score_percentage': score_percentage,
        }
    })