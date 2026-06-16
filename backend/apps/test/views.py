# tests/views.py
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.db import transaction
from functools import wraps
import json
import logging

from apps.test.models import Test, Question, Answer
from apps.results.models import Result
from apps.shared.models import get_main_topics, get_sub_topics, get_predefined_levels, insert_or_update_topic, delete_orphaned_topics, invalidate_topics_cache

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

# ====== Funciones Auxiliares ======

def test_to_dict(test, include_answers=True):
    """Convierte un objeto Test a diccionario con sus relaciones (optimizado)"""
    test_dict = {
        'id': test.id,
        'title': test.title,
        'description': test.description,
        'main_topic': test.main_topic,
        'sub_topic': test.sub_topic,
        'specific_topic': test.specific_topic,
        'level': test.level,
        'is_active': test.is_active,
        'created_by': test.created_by.id if test.created_by else None,
        'created_at': test.created_at.isoformat() if test.created_at else None,
        'updated_at': test.updated_at.isoformat() if test.updated_at else None,
    }
    
    if include_answers and hasattr(test, 'questions_prefetched'):
        # Usar datos precargados para evitar consultas adicionales
        test_dict['questions'] = [
            {
                'id': q.id,
                'question_text': q.question_text,
                'answers': [
                    {
                        'id': a.id,
                        'answer_text': a.answer_text,
                        'is_correct': a.is_correct if include_answers else False
                    }
                    for a in q.answers.all()
                ]
            }
            for q in test.questions_prefetched
        ]
    elif include_answers and hasattr(test, 'questions'):
        # Consulta normal (menos eficiente)
        test_dict['questions'] = [
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
    
    return test_dict

def calculate_score(answers, test_id):
    """Calcula la puntuación de un test (optimizado)"""
    if not answers:
        return 0, 0
    
    # Obtener todas las respuestas correctas de una sola consulta
    correct_answers = Answer.objects.filter(
        question__test_id=test_id,
        is_correct=True
    ).select_related('question').values_list('question_id', 'id')
    
    correct_map = {q_id: a_id for q_id, a_id in correct_answers}
    
    correct_count = 0
    wrong_count = 0
    
    for question_id, user_answer_id in answers.items():
        try:
            q_id = int(question_id)
            u_answer_id = int(user_answer_id)
            if correct_map.get(q_id) == u_answer_id:
                correct_count += 1
            else:
                wrong_count += 1
        except (ValueError, TypeError):
            wrong_count += 1
    
    return correct_count, wrong_count

def get_pagination_params(request):
    """Obtiene y valida parámetros de paginación"""
    try:
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
    except ValueError:
        page, page_size = 1, 10
    
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 50:
        page_size = 10
    
    return page, page_size

# ====== Vistas de Tests ======

@require_http_methods(["GET"])
@login_required
def get_test_by_id(request, test_id):
    """Obtener test por ID con preguntas y respuestas"""
    try:
        # Optimizar consulta precargando relaciones
        test = Test.objects.prefetch_related(
            'questions__answers'
        ).get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    # Cachear las preguntas precargadas
    test.questions_prefetched = test.questions.all()
    
    return JsonResponse({'test': test_to_dict(test)})

@require_http_methods(["GET"])
@login_required
def get_not_started_tests(request):
    """Obtener tests no iniciados por el usuario con filtros y paginación"""
    
    user_id = request.user.id
    page, page_size = get_pagination_params(request)
    
    # Obtener parámetros de filtrado
    main_topic = request.GET.get('main_topic', '')
    level = request.GET.get('level', '')
    sort_by = request.GET.get('sort_by', 'test_created_at')
    sort_order = request.GET.get('sort_order', 'desc')
    
    # Validar campos de ordenación
    sort_mapping = {
        'test_title': 'title',
        'test_level': 'level',
        'test_created_at': 'created_at',
        'test_updated_at': 'updated_at'
    }
    order_field = sort_mapping.get(sort_by, 'created_at')
    if sort_order == 'desc':
        order_field = f'-{order_field}'
    
    # Obtener tests con resultados del usuario (una sola consulta)
    user_result_test_ids = set(
        Result.objects.filter(user_id=user_id)
        .values_list('test_id', flat=True)
        .distinct()
    )
    
    # Construir consulta base
    query = Test.objects.filter(is_active=True).exclude(id__in=user_result_test_ids)
    
    # Calcular estadísticas de nivel (antes de filtrar)
    level_counts = dict(
        query.values('level')
        .annotate(count=Count('id'))
        .values_list('level', 'count')
    )
    total_tests = sum(level_counts.values())
    
    # Aplicar filtros
    if main_topic and main_topic != 'all':
        query = query.filter(main_topic=main_topic)
    if level and level != 'all':
        query = query.filter(level=level)
    
    total_filtered_tests = query.count()
    query = query.order_by(order_field)
    
    # Paginar y optimizar con annotate
    paginator = Paginator(query, page_size)
    page_obj = paginator.get_page(page)
    
    # Obtener conteos de preguntas en una sola consulta
    test_ids = [test.id for test in page_obj]
    question_counts = dict(
        Question.objects.filter(test_id__in=test_ids)
        .values('test_id')
        .annotate(count=Count('id'))
        .values_list('test_id', 'count')
    )
    
    # Construir respuesta
    tests_data = [{
        'id': test.id,
        'title': test.title,
        'description': test.description,
        'main_topic': test.main_topic,
        'sub_topic': test.sub_topic,
        'specific_topic': test.specific_topic,
        'level': test.level,
        'is_active': test.is_active,
        'created_by': test.created_by.id if test.created_by else None,
        'created_at': test.created_at.isoformat(),
        'updated_at': test.updated_at.isoformat(),
        'total_questions': question_counts.get(test.id, 0)
    } for test in page_obj]
    
    return JsonResponse({
        'data': {
            'tests': tests_data,
            'total_tests': total_tests,
            'total_pages': paginator.num_pages,
            'current_page': page,
            'page_size': page_size,
            'has_more': page < paginator.num_pages,
            'main_topics': get_main_topics(),
        },
        'stats': {
            'total_tests': total_tests,
            'total_filtered_tests': total_filtered_tests,
            'total_by_level': level_counts,
        }
    })

@csrf_exempt
@require_http_methods(["POST"])
@login_required
def save_or_update_result(request, test_id):
    """Guardar o actualizar resultado (progreso o finalización)"""
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    # Validar campos requeridos
    status = data.get('status')
    if not status or status not in ['in_progress', 'completed', 'expired']:
        return JsonResponse({'error': 'status debe ser in_progress, completed o expired'}, status=400)
    
    # Verificar que el test existe
    try:
        test = Test.objects.only('id').get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    user_id = request.user.id
    answers = data.get('answers', {})
    time_taken = data.get('time_taken', 0)
    
    # Buscar resultado existente en progreso
    result = Result.objects.filter(
        user_id=user_id,
        test_id=test_id,
        status='in_progress'
    ).first()
    
    # Calcular puntuación solo si está completado
    correct_count = wrong_count = 0
    if status == 'completed' and answers:
        correct_count, wrong_count = calculate_score(answers, test_id)
    
    # Preparar datos
    answers_json = json.dumps(answers) if answers else ''
    
    if result:
        # Actualizar resultado existente
        result.status = status
        result.time_taken = time_taken
        result.updated_at = timezone.now()
        
        if status == 'completed':
            result.correct_answers = correct_count
            result.wrong_answers = wrong_count
        
        if answers:
            result.answers = answers_json
        
        result.save()
    else:
        # Crear nuevo resultado
        result = Result.objects.create(
            user_id=user_id,
            test_id=test_id,
            status=status,
            time_taken=time_taken,
            correct_answers=correct_count,
            wrong_answers=wrong_count,
            answers=answers_json
        )
    
    # Calcular respuesta
    total_answers = len(answers)
    score_percentage = (correct_count / total_answers * 100) if total_answers > 0 else 0
    
    return JsonResponse({
        'message': 'Resultado guardado exitosamente',
        'result_id': result.pk,
        'test_id': result.test_id,
        'status': result.status,
        'correct_answers': result.correct_answers,
        'wrong_answers': result.wrong_answers,
        'total': total_answers,
        'time_taken': result.time_taken,
        'score_percentage': round(score_percentage, 2)
    })

@require_http_methods(["GET"])
@login_required
def get_test_progress(request, test_id):
    """Obtener progreso actual de un test (optimizado)"""
    
    user_id = request.user.id
    
    # Buscar resultado en progreso
    result = Result.objects.filter(
        user_id=user_id,
        test_id=test_id,
        status='in_progress'
    ).first()
    
    # Obtener test con relaciones precargadas
    try:
        test = Test.objects.prefetch_related('questions__answers').get(id=test_id)
        test.questions_prefetched = test.questions.all()
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
    
    # Decodificar respuestas guardadas
    saved_answers = {}
    if result.answers:
        try:
            saved_answers = json.loads(result.answers)
        except json.JSONDecodeError:
            pass
    
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

@require_http_methods(["GET"])
@login_required
def get_my_in_progress_tests(request):
    """Obtener tests en progreso del usuario actual (optimizado)"""
    
    user_id = request.user.id
    page, page_size = get_pagination_params(request)
    
    # Obtener parámetros
    main_topic = request.GET.get('main_topic', '')
    level = request.GET.get('level', '')
    sort_by = request.GET.get('sort_by', 'result_updated_at')
    sort_order = request.GET.get('sort_order', 'desc')
    
    # Mapeo de ordenación
    sort_mapping = {
        'result_updated_at': 'updated_at',
        'result_started_at': 'started_at',
        'result_time_taken': 'time_taken',
        'test_title': 'test__title',
        'test_created_at': 'test__created_at',
        'test_level': 'test__level'
    }
    order_field = sort_mapping.get(sort_by, 'updated_at')
    if sort_order == 'desc':
        order_field = f'-{order_field}'
    
    # Construir consulta base con select_related
    query = Result.objects.filter(
        user_id=user_id,
        status='in_progress'
    ).select_related('test')
    
    # Aplicar filtros
    if main_topic:
        query = query.filter(test__main_topic=main_topic)
    if level:
        query = query.filter(test__level=level)
    
    total_filtered_tests = query.count()
    query = query.order_by(order_field)
    
    # Paginar
    paginator = Paginator(query, page_size)
    page_obj = paginator.get_page(page)
    
    # Procesar resultados
    results_data = []
    total_progress = 0
    total_answered = 0
    
    for result in page_obj:
        answers = {}
        if result.answers:
            try:
                answers = json.loads(result.answers)
            except json.JSONDecodeError:
                pass
        
        answered_count = len(answers)
        total_questions = result.test.questions.count()
        progress = (answered_count / total_questions * 100) if total_questions > 0 else 0
        
        total_progress += progress
        total_answered += answered_count
        
        # Formatear tiempo
        time_spent = format_time(result.time_taken)
        
        results_data.append({
            'result_id': result.id,
            'user_id': result.user_id,
            'test_id': result.test.id,
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
            'progress': round(progress, 2),
            'answered_count': answered_count,
            'remaining_count': total_questions - answered_count,
            'time_spent': time_spent
        })
    
    # Calcular estadísticas
    avg_progress = (total_progress / len(results_data)) if results_data else 0
    total_time = sum(r.time_taken for r in page_obj)
    
    # Obtener temas principales únicos
    main_topics = list(
        Result.objects.filter(user_id=user_id, status='in_progress')
        .exclude(test__main_topic='')
        .values_list('test__main_topic', flat=True)
        .distinct()
        .order_by('test__main_topic')
    )
    
    return JsonResponse({
        'data': {
            'results': results_data,
            'total_tests': Result.objects.filter(user_id=user_id, status='in_progress').count(),
            'total_pages': paginator.num_pages,
            'current_page': page,
            'page_size': page_size,
            'has_more': page < paginator.num_pages,
            'main_topics': main_topics
        },
        'stats': {
            'total_filtered_tests': total_filtered_tests,
            'average_progress': round(avg_progress, 2),
            'total_questions_answered': total_answered,
            'total_time_spent': total_time,
            'avg_time_per_test': total_time // total_filtered_tests if total_filtered_tests > 0 else 0
        }
    })

@require_http_methods(["GET"])
@login_required
def get_my_completed_tests(request):
    """Obtener tests completados del usuario actual (optimizado)"""
    
    user_id = request.user.id
    page, page_size = get_pagination_params(request)
    
    # Obtener parámetros
    main_topic = request.GET.get('main_topic', '')
    level = request.GET.get('level', '')
    sort_by = request.GET.get('sort_by', 'result_updated_at')
    sort_order = request.GET.get('sort_order', 'desc')
    
    # Mapeo de ordenación
    sort_mapping = {
        'result_updated_at': 'updated_at',
        'result_started_at': 'started_at',
        'result_time_taken': 'time_taken',
        'test_title': 'test__title',
        'test_created_at': 'test__created_at',
        'test_level': 'test__level'
    }
    order_field = sort_mapping.get(sort_by, 'updated_at')
    if sort_order == 'desc' and sort_by != 'score':
        order_field = f'-{order_field}'
    
    # Construir consulta base
    query = Result.objects.filter(
        user_id=user_id,
        status='completed',
        test__is_active=True
    ).select_related('test')
    
    # Aplicar filtros
    if main_topic:
        query = query.filter(test__main_topic=main_topic)
    if level:
        query = query.filter(test__level=level)
    
    total_filtered_tests = query.count()
    
    if sort_by != 'score':
        query = query.order_by(order_field)
    else:
        query = query.order_by('-updated_at')
    
    # Paginar
    paginator = Paginator(query, page_size)
    page_obj = paginator.get_page(page)
    
    # Procesar resultados
    results_data = []
    for result in page_obj:
        total_questions = result.test.questions.count()
        score_percent = (result.correct_answers / total_questions * 100) if total_questions > 0 else 0
        
        total_answered = result.correct_answers + result.wrong_answers
        accuracy = (result.correct_answers / total_answered * 100) if total_answered > 0 else 0
        
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
    
    # Ordenar por score si es necesario
    if sort_by == 'score':
        results_data.sort(key=lambda x: x['score_percent'], reverse=(sort_order == 'desc'))
        
    # Calcular estadísticas generales
    stats_query = query if main_topic or level else Result.objects.filter(user_id=user_id, status='completed')
    stats_query = stats_query.select_related('test')

    total_questions_sum = 0
    total_correct_sum = 0
    total_time_sum = 0

    for result in stats_query.iterator():
        q_count = result.test.questions.count()
        total_questions_sum += q_count
        total_correct_sum += result.correct_answers
        total_time_sum += result.time_taken

    avg_score = (total_correct_sum / total_questions_sum * 100) if total_questions_sum > 0 else 0

    # Obtener temas principales
    main_topics = list(
        Result.objects.filter(user_id=user_id, status='completed')
        .exclude(test__main_topic='')
        .values_list('test__main_topic', flat=True)
        .distinct()
        .order_by('test__main_topic')
    )
    
    return JsonResponse({
        'data': {
            'test_results': results_data,
            'total_tests': Result.objects.filter(user_id=user_id, status='completed').count(),
            'total_pages': paginator.num_pages,
            'current_page': page,
            'page_size': page_size,
            'has_more': page < paginator.num_pages,
            'main_topics': main_topics
        },
        'stats': {
            'average_score': round(avg_score, 2),
            'total_time_spent': total_time_sum,
            'total_filtered_tests': total_filtered_tests,
            'total_questions_answered': total_correct_sum
        }
    })

@require_http_methods(["DELETE"])
@login_required
def delete_test_progress(request, test_id):
    """Eliminar progreso de un test"""
    
    deleted_count, _ = Result.objects.filter(
        user_id=request.user.id,
        test_id=test_id,
        status='in_progress'
    ).delete()
    
    message = 'progreso eliminado' if deleted_count > 0 else 'no se encontró progreso para eliminar'
    return JsonResponse({'message': message})

# ====== Vistas de Preguntas ======

@require_http_methods(["GET"])
@login_required
def get_test_questions(request, test_id):
    """Obtener todas las preguntas de un test (paginadas y optimizadas)"""
    
    # Validar test
    try:
        test = Test.objects.only('id').get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    page, page_size = get_pagination_params(request)
    
    # Obtener progreso del usuario
    result = Result.objects.filter(
        user_id=request.user.id,
        test_id=test_id
    ).exclude(status='completed').first()
    
    # Obtener total de preguntas
    total_questions = Question.objects.filter(test_id=test_id).count()
    
    # Obtener preguntas paginadas con respuestas (excluyendo is_correct)
    questions_query = Question.objects.filter(test_id=test_id).prefetch_related('answers')
    paginator = Paginator(questions_query, page_size)
    page_obj = paginator.get_page(page)
    
    # Construir respuesta
    question_responses = []
    for question in page_obj:
        answers = [{'id': a.id, 'answer_text': a.answer_text} for a in question.answers.all()]
        question_responses.append({
            'id': question.id,
            'question_text': question.question_text,
            'answers': answers
        })
    
    # Calcular progreso
    progress = 0.0
    if result and result.answers:
        try:
            saved_answers = json.loads(result.answers)
            progress = (len(saved_answers) / total_questions * 100) if total_questions > 0 else 0
        except json.JSONDecodeError:
            pass
    
    return JsonResponse({
        'test_id': test_id,
        'total': total_questions,
        'page': page,
        'page_size': page_size,
        'questions': question_responses,
        'progress': round(progress, 2)
    })

@require_http_methods(["GET"])
@login_required
def get_single_question(request, test_id, question_number):
    """Obtener una pregunta específica por número"""
    
    try:
        test_id = int(test_id)
        question_number = int(question_number)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'ID de test o número de pregunta inválido'}, status=400)
    
    if question_number < 1:
        return JsonResponse({'error': 'número de pregunta inválido'}, status=400)
    
    # Verificar test
    if not Test.objects.filter(id=test_id).exists():
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    # Obtener pregunta específica usando offset
    try:
        question = Question.objects.filter(test_id=test_id).prefetch_related('answers').order_by('id')[question_number - 1]
    except IndexError:
        return JsonResponse({'error': 'pregunta no encontrada'}, status=404)
    
    total_questions = Question.objects.filter(test_id=test_id).count()
    answers = [{'id': a.pk, 'answer_text': a.answer_text} for a in question.answers.all()]
    
    return JsonResponse({
        'question': {
            'id': question.pk,
            'question_text': question.question_text,
            'answers': answers
        },
        'question_number': question_number,
        'total_questions': total_questions,
        'has_next': question_number < total_questions,
        'has_previous': question_number > 1
    })

@require_http_methods(["GET"])
@login_required
def get_next_unanswered_question(request, test_id):
    """Obtener la siguiente pregunta sin responder (optimizado)"""
    
    try:
        test_id = int(test_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'ID de test inválido'}, status=400)
    
    # Verificar test
    if not Test.objects.filter(id=test_id).exists():
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    user_id = request.user.id
    
    # Obtener resultado existente
    result = Result.objects.filter(
        user_id=user_id,
        test_id=test_id
    ).exclude(status='completed').first()
    
    # Obtener IDs de preguntas respondidas
    answered_question_ids = set()
    if result and result.answers:
        try:
            saved_answers = json.loads(result.answers)
            answered_question_ids = set(int(qid) for qid in saved_answers.keys())
        except json.JSONDecodeError:
            pass
    
    # Obtener total de preguntas
    total_questions = Question.objects.filter(test_id=test_id).count()
    
    # Verificar si completó todas
    if len(answered_question_ids) >= total_questions:
        return JsonResponse({
            'message': 'todas_las_preguntas_respondidas',
            'is_completed': True,
            'answered_count': len(answered_question_ids),
            'total_questions': total_questions,
            'progress': 100.0
        })
    
    # Obtener siguiente pregunta
    questions_query = Question.objects.filter(test_id=test_id)
    if answered_question_ids:
        questions_query = questions_query.exclude(id__in=answered_question_ids)
    
    question = questions_query.prefetch_related('answers').order_by('id').first()
    
    if not question:
        return JsonResponse({'error': 'no se encontró pregunta sin responder'}, status=404)
    
    # Calcular número de pregunta
    question_number = Question.objects.filter(test_id=test_id, id__lte=question.pk).count()
    answers = [{'id': a.pk, 'answer_text': a.answer_text} for a in question.answers.all()]
    progress = (len(answered_question_ids) / total_questions * 100) if total_questions > 0 else 0
    
    return JsonResponse({
        'question': {
            'id': question.pk,
            'question_text': question.question_text,
            'answers': answers
        },
        'question_number': question_number,
        'total_questions': total_questions,
        'is_completed': False,
        'answered_count': len(answered_question_ids),
        'progress': round(progress, 2)
    })

# ====== Vistas de Administración ======

@csrf_exempt
@require_http_methods(["POST"])
@admin_required
def create_test(request):
    """Crear un nuevo test (solo admin)"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    # Validaciones
    required_fields = ['title', 'main_topic', 'sub_topic', 'specific_topic', 'level', 'questions']
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return JsonResponse({'error': f'Campos requeridos faltantes: {", ".join(missing_fields)}'}, status=400)
    
    # Validar nivel
    valid_levels = get_predefined_levels()
    if data['level'] not in valid_levels:
        return JsonResponse({
            'error': 'Nivel no válido',
            'valid_levels': valid_levels
        }, status=400)
    
    # Validar preguntas
    validation_error = validate_questions(data['questions'])
    if validation_error:
        return JsonResponse({'error': validation_error}, status=400)
    
    # Crear test en transacción
    with transaction.atomic():
        test = Test.objects.create(
            title=data['title'],
            description=data.get('description', ''),
            main_topic=data['main_topic'],
            sub_topic=data['sub_topic'],
            specific_topic=data['specific_topic'],
            level=data['level'],
            is_active=data.get('is_active', True),
            created_by=request.user,
        )
        
        # Crear preguntas y respuestas
        for q_data in data['questions']:
            question = Question.objects.create(test=test, question_text=q_data['question_text'])
            
            for a_data in q_data.get('answers', []):
                Answer.objects.create(
                    question=question,
                    answer_text=a_data['answer_text'],
                    is_correct=a_data.get('is_correct', False)
                )
    
    # Actualizar temas
    try:
        insert_or_update_topic(data['main_topic'], data['sub_topic'], data['specific_topic'], is_predefined=False)
        invalidate_topics_cache()
    except Exception as e:
        logger.warning(f"No se pudo guardar nuevo tema: {str(e)}")
    
    # Obtener test creado
    created_test = Test.objects.prefetch_related('questions__answers').get(id=test.pk)
    created_test.questions_prefetched = created_test.questions.all()
    
    return JsonResponse({
        'test': test_to_dict(created_test),
        'message': 'Test creado exitosamente'
    }, status=201)

@csrf_exempt
@require_http_methods(["PUT", "PATCH"])
@admin_required
def update_test(request, test_id):
    """Actualizar un test existente"""
    
    try:
        existing_test = Test.objects.get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    # Validar nivel si se proporciona
    if 'level' in data and data['level']:
        valid_levels = get_predefined_levels()
        if data['level'] not in valid_levels:
            return JsonResponse({
                'error': 'Nivel no válido',
                'valid_levels': valid_levels
            }, status=400)
    
    # Validar preguntas si se proporcionan
    if 'questions' in data and data['questions']:
        validation_error = validate_questions(data['questions'], is_update=True)
        if validation_error:
            return JsonResponse({'error': validation_error}, status=400)
    
    # Actualizar en transacción
    with transaction.atomic():
        # Actualizar campos básicos
        update_fields = ['title', 'description', 'main_topic', 'sub_topic', 'specific_topic', 'level', 'is_active']
        for field in update_fields:
            if field in data:
                setattr(existing_test, field, data[field])
        
        existing_test.updated_at = timezone.now()
        existing_test.save()
        
        # Procesar preguntas si se proporcionan
        if 'questions' in data and data['questions']:
            update_questions(existing_test, data['questions'])
    
    # Actualizar temas
    try:
        insert_or_update_topic(existing_test.main_topic, existing_test.sub_topic, existing_test.specific_topic, is_predefined=False)
        invalidate_topics_cache()
        delete_orphaned_topics()
    except Exception as e:
        logger.warning(f"Error actualizando temas: {str(e)}")
    
    # Obtener test actualizado
    updated_test = Test.objects.prefetch_related('questions__answers').get(id=test_id)
    updated_test.questions_prefetched = updated_test.questions.all()
    
    return JsonResponse({
        'test': test_to_dict(updated_test),
        'message': 'Test actualizado correctamente'
    })

@require_http_methods(["DELETE"])
@admin_required
@csrf_exempt
def delete_test(request, test_id):
    """Eliminar un test"""
    try:
        test = Test.objects.get(id=test_id)
    except Test.DoesNotExist:
        return JsonResponse({'error': 'test no encontrado'}, status=404)
    
    # Eliminar en transacción
    with transaction.atomic():
        # Eliminar resultados y respuestas asociadas
        Result.objects.filter(test_id=test_id).delete()
        
        # Intentar importar TestInvitation solo si existe
        try:
            from apps.invitations.models import TestInvitation
            TestInvitation.objects.filter(test_id=test_id).delete()
        except ImportError:
            pass  # Si no existe el modelo, continuar
        
        # Eliminar test (las preguntas y respuestas se eliminan en cascada)
        test.delete()
    
    # Limpiar temas huérfanos
    try:
        delete_orphaned_topics()
        invalidate_topics_cache()
    except Exception as e:
        logger.warning(f"No se pudieron eliminar topics huérfanos: {str(e)}")
    
    return JsonResponse({'message': 'Test eliminado correctamente'})

@require_http_methods(["GET"])
@admin_required
def get_all_tests(request):
    """Obtener todos los tests con paginación, filtrado y ordenación"""
    
    page, page_size = get_pagination_params(request)
    page_size = min(page_size, 100)  # Limitar a 100 máximo
    
    # Obtener parámetros
    sort_by = request.GET.get('sort_by', 'created_at')
    sort_order = request.GET.get('sort_order', 'desc')
    main_topic = request.GET.get('main_topic', '')
    sub_topic = request.GET.get('sub_topic', '')
    level = request.GET.get('level', '')
    is_active_param = request.GET.get('is_active')
    search = request.GET.get('search', '')
    
    # Validar campos de ordenación
    valid_sort_fields = ['id', 'title', 'main_topic', 'sub_topic', 'level', 'is_active', 'updated_at', 'created_at', 'created_by']
    if sort_by not in valid_sort_fields:
        sort_by = 'created_at'
    
    order_field = f'-{sort_by}' if sort_order == 'desc' else sort_by
    
    # Construir consulta
    query = Test.objects.annotate(question_count=Count('questions')).select_related('created_by')
    
    # Aplicar filtros
    if main_topic:
        query = query.filter(main_topic=main_topic)
    if sub_topic:
        query = query.filter(sub_topic=sub_topic)
    if level:
        query = query.filter(level=level)
    if is_active_param is not None:
        query = query.filter(is_active=is_active_param.lower() == 'true')
    if search:
        query = query.filter(Q(title__icontains=search) | Q(description__icontains=search))
    
    total_tests = Test.objects.count()
    total_filtered_tests = query.count()
    
    # Ordenar y paginar
    query = query.order_by(order_field)
    paginator = Paginator(query, page_size)
    page_obj = paginator.get_page(page)
    
    # Construir respuesta
    tests_data = []
    for test in page_obj:
        test_dict = {
            'id': test.id,
            'title': test.title,
            'description': test.description,
            'main_topic': test.main_topic,
            'sub_topic': test.sub_topic,
            'specific_topic': test.specific_topic,
            'level': test.level,
            'is_active': test.is_active,
            'created_by': test.created_by.id if test.created_by else None,
            'created_by_username': test.created_by.username if test.created_by else None,
            'created_at': test.created_at.isoformat() if test.created_at else None,
            'updated_at': test.updated_at.isoformat() if test.updated_at else None,
            'question_count': test.question_count
        }
        tests_data.append(test_dict)
    
    # Obtener filtros disponibles
    main_topics = get_main_topics()
    sub_topics = get_sub_topics(main_topic) if main_topic else []
    levels = get_predefined_levels()
    
    return JsonResponse({
        'tests': tests_data,
        'filters_applied': {
            'page': page,
            'page_size': page_size,
            'main_topic': main_topic,
            'sub_topic': sub_topic,
            'level': level,
            'is_active': is_active_param,
            'search': search,
            'sort_by': sort_by,
            'sort_order': sort_order
        },
        'available_filters': {
            'main_topics': main_topics,
            'sub_topics': sub_topics,
            'levels': levels,
            'statuses': ['Activo', 'Inactivo']
        },
        'stats': {
            'total_tests': total_tests,
            'total_filtered_tests': total_filtered_tests
        }
    })

# ====== Funciones Auxiliares Adicionales ======

def format_time(seconds):
    """Formatea segundos en formato legible"""
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

def validate_questions(questions_data, is_update=False):
    """Valida las preguntas de un test"""
    if not questions_data:
        return 'El test debe contener al menos una pregunta'
    
    for i, question in enumerate(questions_data):
        question_text = question.get('question_text', '').strip()
        
        # Para preguntas nuevas, validar texto
        if not is_update or question.get('id', 0) == 0:
            if not question_text:
                return f'La pregunta {i+1} no tiene texto'
        
        answers = question.get('answers', [])
        if not is_update or question.get('id', 0) == 0:
            if len(answers) < 2:
                return f'La pregunta {i+1} debe tener al menos 2 respuestas'
        
        # Validar respuestas
        correct_count = 0
        for j, answer in enumerate(answers):
            answer_text = answer.get('answer_text', '').strip()
            if not answer_text and answer.get('id', 0) == 0:
                return f'La respuesta {j+1} de la pregunta {i+1} no tiene texto'
            if answer.get('is_correct', False):
                correct_count += 1
        
        if correct_count != 1:
            return f'La pregunta {i+1} debe tener exactamente una respuesta correcta (tiene {correct_count})'
    
    return None

def update_questions(test, questions_data):
    """Actualiza las preguntas de un test"""
    # Obtener IDs de preguntas existentes
    existing_question_ids = list(test.questions.values_list('id', flat=True))
    
    for q_data in questions_data:
        question_id = q_data.get('id', 0)
        
        if question_id == 0:
            # Crear nueva pregunta
            question = Question.objects.create(test=test, question_text=q_data['question_text'])
            
            for a_data in q_data.get('answers', []):
                Answer.objects.create(
                    question=question,
                    answer_text=a_data['answer_text'],
                    is_correct=a_data.get('is_correct', False)
                )
        else:
            # Actualizar pregunta existente
            try:
                question = Question.objects.get(id=question_id, test=test)
            except Question.DoesNotExist:
                continue
            
            if q_data.get('question_text'):
                question.question_text = q_data['question_text']
                question.save()
            
            # Procesar respuestas
            if 'answers' in q_data and q_data['answers']:
                existing_answer_ids = list(question.answers.values_list('id', flat=True))
                
                for a_data in q_data['answers']:
                    answer_id = a_data.get('id', 0)
                    
                    if answer_id == 0:
                        # Nueva respuesta
                        Answer.objects.create(
                            question=question,
                            answer_text=a_data['answer_text'],
                            is_correct=a_data.get('is_correct', False)
                        )
                    else:
                        # Actualizar respuesta existente
                        try:
                            answer = Answer.objects.get(id=answer_id, question=question)
                            if a_data.get('answer_text'):
                                answer.answer_text = a_data['answer_text']
                            answer.is_correct = a_data.get('is_correct', answer.is_correct)
                            answer.save()
                            
                            if answer_id in existing_answer_ids:
                                existing_answer_ids.remove(answer_id)
                        except Answer.DoesNotExist:
                            continue
                
                # Eliminar respuestas que no están en el input
                if existing_answer_ids:
                    Answer.objects.filter(id__in=existing_answer_ids).delete()
            
            # Remover de la lista de IDs existentes
            if question_id in existing_question_ids:
                existing_question_ids.remove(question_id)
    
    # Eliminar preguntas que no están en el input
    if existing_question_ids:
        Question.objects.filter(id__in=existing_question_ids).delete()