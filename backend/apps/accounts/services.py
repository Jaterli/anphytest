# users/services.py
from django.db.models import Count, Sum, Min, Avg, Q, F, Value, OuterRef, Subquery
from django.db.models.functions import Coalesce, Round
from django.contrib.auth import get_user_model
from apps.results.models import Result

User = get_user_model()

# Constantes
MIN_TESTS_FOR_RANKING = 5
PREDEFINED_LEVELS = ['Principiante', 'Intermedio', 'Avanzado']

# Tipos de métricas
METRIC_TESTS_COUNT = 'completed_tests'
METRIC_AVG_TIME = 'time'
METRIC_ACCURACY = 'accuracy'
METRIC_QUESTIONS_ANSWERED = 'questions_answered'


class DataService:
    """Servicio para obtener datos estadísticos del usuario y comunidad"""
    
    def _get_first_attempt_subquery(self, user_id=None, level=None):
        """
        Helper para obtener subconsulta de primeros intentos de forma eficiente.
        Retorna un Subquery con los IDs de los primeros intentos.
        """
        first_attempts = Result.objects.filter(
            status='completed'
        ).values('user_id', 'test_id').annotate(
            first_updated=Min('updated_at')
        )
        
        if user_id:
            first_attempts = first_attempts.filter(user_id=user_id)
        
        if level:
            first_attempts = first_attempts.filter(test__level=level)
        
        # Subconsulta para obtener los IDs de resultados
        return Result.objects.filter(
            user_id=OuterRef('user_id'),
            test_id=OuterRef('test_id'),
            updated_at=OuterRef('first_updated')
        ).values('id')[:1]
    
    def get_personal_data(self, user_id):
        """Obtiene estadísticas personales del usuario - OPTIMIZADO"""
        
        # Obtener first_attempt_ids de una sola vez usando subquery
        first_attempt_subquery = Result.objects.filter(
            user_id=user_id,
            status='completed'
        ).values('test_id').annotate(
            first_updated=Min('updated_at')
        )
        
        first_attempt_ids = Result.objects.filter(
            user_id=user_id,
            status='completed',
            updated_at=Subquery(first_attempt_subquery.values('first_updated')[:1])
        ).values_list('id', flat=True)
        
        # Una sola consulta para ambos agregados
        from django.db import connection
        
        # Optimización: usar una sola consulta con UNION o dos consultas simples
        # Ya que son agregados distintos, dos consultas separadas son más claras y eficientes
        
        # Todos los intentos
        all_attempts = Result.objects.filter(
            user_id=user_id,
            status='completed'
        ).aggregate(
            tests_count=Count('test_id', distinct=True),
            total_correct=Coalesce(Sum('correct_answers'), Value(0)),
            total_wrong=Coalesce(Sum('wrong_answers'), Value(0)),
            total_time=Coalesce(Sum('time_taken'), Value(0)),
            total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0))
        )
        
        # Primeros intentos
        first_attempt_data = Result.objects.filter(
            id__in=first_attempt_ids
        ).aggregate(
            tests_count=Count('test_id', distinct=True),
            total_correct=Coalesce(Sum('correct_answers'), Value(0)),
            total_wrong=Coalesce(Sum('wrong_answers'), Value(0)),
            total_time=Coalesce(Sum('time_taken'), Value(0)),
            total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0))
        )
        
        # Contar estados (optimizado con una sola consulta)
        status_counts = Result.objects.filter(user_id=user_id).aggregate(
            total_completed=Count('id', filter=Q(status='completed')),
            total_in_progress=Count('id', filter=Q(status='in_progress')),
            total_expired=Count('id', filter=Q(status='expired'))
        )
        
        return {
            'completed_tests': status_counts['total_completed'],
            'in_progress_tests': status_counts['total_in_progress'],
            'expired_tests': status_counts['total_expired'],
            'all_attempts': {
                'tests_count': all_attempts['tests_count'],
                'total_correct': all_attempts['total_correct'],
                'total_wrong': all_attempts['total_wrong'],
                'total_time_taken': all_attempts['total_time'],
                'total_questions_answered': all_attempts['total_questions'],
            },
            'first_attempt': {
                'tests_count': first_attempt_data['tests_count'],
                'total_correct': first_attempt_data['total_correct'],
                'total_wrong': first_attempt_data['total_wrong'],
                'total_time_taken': first_attempt_data['total_time'],
                'total_questions_answered': first_attempt_data['total_questions'],
            }
        }
    
    def get_personal_level_data(self, user_id):
        """Obtiene estadísticas por nivel del usuario - OPTIMIZADO"""
        
        level_data = {}
        
        for level in PREDEFINED_LEVELS:
            # Obtener first_attempt_ids para este nivel
            first_attempt_subquery = Result.objects.filter(
                user_id=user_id,
                status='completed',
                test__level=level
            ).values('test_id').annotate(
                first_updated=Min('updated_at')
            )
            
            first_attempt_ids = Result.objects.filter(
                user_id=user_id,
                status='completed',
                test__level=level,
                updated_at=Subquery(first_attempt_subquery.values('first_updated')[:1])
            ).values_list('id', flat=True)
            
            # Todos los intentos
            all_attempts = Result.objects.filter(
                user_id=user_id,
                status='completed',
                test__level=level
            ).aggregate(
                tests_count=Count('test_id', distinct=True),
                questions_count=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0)),
                total_correct=Coalesce(Sum('correct_answers'), Value(0)),
                total_wrong=Coalesce(Sum('wrong_answers'), Value(0)),
                total_time_taken=Coalesce(Sum('time_taken'), Value(0))
            )
            
            # Primeros intentos
            first_attempt = Result.objects.filter(
                id__in=first_attempt_ids
            ).aggregate(
                tests_count=Count('test_id', distinct=True),
                questions_count=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0)),
                total_correct=Coalesce(Sum('correct_answers'), Value(0)),
                total_wrong=Coalesce(Sum('wrong_answers'), Value(0)),
                total_time_taken=Coalesce(Sum('time_taken'), Value(0))
            )
            
            level_data[level] = {
                'first_attempt': {
                    'tests_count': first_attempt['tests_count'],
                    'questions_count': first_attempt['questions_count'],
                    'total_correct': first_attempt['total_correct'],
                    'total_wrong': first_attempt['total_wrong'],
                    'total_time_taken': first_attempt['total_time_taken'],
                },
                'all_attempts': {
                    'tests_count': all_attempts['tests_count'],
                    'questions_count': all_attempts['questions_count'],
                    'total_correct': all_attempts['total_correct'],
                    'total_wrong': all_attempts['total_wrong'],
                    'total_time_taken': all_attempts['total_time_taken'],
                }
            }
        
        return level_data
    
    def get_active_users_count(self):
        """Obtiene usuarios con al menos MIN_TESTS_FOR_RANKING tests diferentes completados"""
        return Result.objects.filter(
            status='completed'
        ).values('user_id').annotate(
            test_count=Count('test_id', distinct=True)
        ).filter(test_count__gte=MIN_TESTS_FOR_RANKING).count()
    
    def get_top_by_metric(self, metric, limit=10, level=None, min_tests=MIN_TESTS_FOR_RANKING):
        """Obtiene top por métrica específica"""
        
        if metric == 'top_by_tests':
            return self._get_top_by_tests(limit, min_tests)
        elif metric == 'top_by_level':
            return self._get_top_by_level(level, limit, min_tests)
        elif metric == 'top_by_levels_accuracy':
            return self._get_top_by_levels_accuracy_optimized(level, limit, min_tests)
        return []
    
    def _get_top_by_tests(self, limit, min_tests):
        """Obtiene top por cantidad de tests completados"""
        results = Result.objects.filter(
            status='completed'
        ).values('user_id', 'user__username').annotate(
            value=Count('test_id', distinct=True)
        ).filter(value__gt=min_tests).order_by('-value')[:limit]
        
        return [{'user_id': item['user_id'], 'username': item['user__username'], 
                 'value': item['value'], 'rank': idx + 1} 
                for idx, item in enumerate(results)]
    
    def _get_top_by_level(self, level, limit, min_tests):
        """Obtiene top por nivel"""
        results = Result.objects.filter(
            status='completed',
            test__level=level
        ).values('user_id', 'user__username').annotate(
            value=Count('test_id', distinct=True)
        ).filter(value__gt=min_tests).order_by('-value')[:limit]
        
        return [{'user_id': item['user_id'], 'username': item['user__username'], 
                 'value': item['value'], 'rank': idx + 1} 
                for idx, item in enumerate(results)]
    
    def _get_top_by_levels_accuracy_optimized(self, level, limit, min_tests):
        """
        Obtiene top por precisión por nivel - VERSIÓN OPTIMIZADA
        Usa una sola consulta con subquery en lugar de múltiples consultas
        """
        # Subquery para obtener el primer intento de cada test por usuario
        first_attempt_subquery = Result.objects.filter(
            status='completed',
            test__level=level,
            user_id=OuterRef('user_id'),
            test_id=OuterRef('test_id')
        ).order_by('updated_at').values('id')[:1]
        
        # Consulta principal agrupada por usuario
        results = Result.objects.filter(
            status='completed',
            test__level=level,
            id=Subquery(first_attempt_subquery)
        ).values('user_id', 'user__username').annotate(
            total_correct=Sum('correct_answers'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(
            total_questions__gt=0
        ).annotate(
            value=Round(F('total_correct') * 100.0 / F('total_questions'), 2)
        ).filter(
            value__gt=0
        ).order_by('-value')[:limit]
        
        return [{'user_id': item['user_id'], 'username': item['user__username'],
                 'value': float(item['value']), 'rank': idx + 1}
                for idx, item in enumerate(results)]
    
    def get_top_by_avg_time(self, attempt_type='all', limit=10):
        """Obtiene top por tiempo promedio por pregunta - OPTIMIZADO"""
        
        query = Result.objects.filter(status='completed')
        
        if attempt_type == 'first':
            # Subquery optimizada para primeros intentos
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            query = query.filter(id=Subquery(first_attempt_subquery))
        
        results = query.values('user_id', 'user__username').annotate(
            total_time=Sum('time_taken'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(
            total_questions__gt=0
        ).annotate(
            value=Round(F('total_time') * 1.0 / F('total_questions'), 2)
        ).order_by('value')[:limit]
        
        return [{'user_id': item['user_id'], 'username': item['user__username'],
                 'value': float(item['value']), 'rank': idx + 1}
                for idx, item in enumerate(results)]
    
    def get_top_by_accuracy(self, attempt_type='all', limit=10):
        """Obtiene top por precisión - OPTIMIZADO"""
        
        query = Result.objects.filter(status='completed')
        
        if attempt_type == 'first':
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            query = query.filter(id=Subquery(first_attempt_subquery))
        
        results = query.values('user_id', 'user__username').annotate(
            total_correct=Sum('correct_answers'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(
            total_questions__gt=0
        ).annotate(
            value=Round(F('total_correct') * 100.0 / F('total_questions'), 2)
        ).order_by('-value')[:limit]
        
        return [{'user_id': item['user_id'], 'username': item['user__username'],
                 'value': float(item['value']), 'rank': idx + 1}
                for idx, item in enumerate(results)]
    
    def get_top_by_questions_answered(self, attempt_type='all', limit=10):
        """Obtiene top por preguntas respondidas - OPTIMIZADO"""
        
        query = Result.objects.filter(status='completed')
        
        if attempt_type == 'first':
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            query = query.filter(id=Subquery(first_attempt_subquery))
        
        results = query.values('user_id', 'user__username').annotate(
            value=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0))
        ).filter(value__gt=0).order_by('-value')[:limit]
        
        return [{'user_id': item['user_id'], 'username': item['user__username'],
                 'value': item['value'], 'rank': idx + 1}
                for idx, item in enumerate(results)]
    
    def get_community_averages(self):
        """Obtiene promedios de la comunidad - OPTIMIZADO"""
        
        # Usuarios con suficientes tests
        active_users = Result.objects.filter(
            status='completed'
        ).values('user_id').annotate(
            test_count=Count('test_id', distinct=True)
        ).filter(test_count__gte=MIN_TESTS_FOR_RANKING).values_list('user_id', flat=True)
        
        if not active_users:
            return self._get_empty_averages()
        
        # Subquery para primeros intentos
        first_attempt_subquery = Result.objects.filter(
            status='completed',
            user_id=OuterRef('user_id'),
            test_id=OuterRef('test_id')
        ).order_by('updated_at').values('id')[:1]
        
        # Todos los intentos - una sola consulta
        all_stats = Result.objects.filter(
            user_id__in=active_users,
            status='completed'
        ).aggregate(
            total_time=Coalesce(Sum('time_taken'), Value(0)),
            total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0)),
            total_correct=Coalesce(Sum('correct_answers'), Value(0))
        )
        
        # Primeros intentos
        first_stats = Result.objects.filter(
            user_id__in=active_users,
            status='completed',
            id=Subquery(first_attempt_subquery)
        ).aggregate(
            total_time=Coalesce(Sum('time_taken'), Value(0)),
            total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0)),
            total_correct=Coalesce(Sum('correct_answers'), Value(0))
        )
        
        # Calcular promedios (evitar división por cero)
        avg_time_all = round(all_stats['total_time'] / all_stats['total_questions'], 2) if all_stats['total_questions'] > 0 else 0
        avg_time_first = round(first_stats['total_time'] / first_stats['total_questions'], 2) if first_stats['total_questions'] > 0 else 0
        
        avg_accuracy_all = round((all_stats['total_correct'] / all_stats['total_questions']) * 100, 2) if all_stats['total_questions'] > 0 else 0
        avg_accuracy_first = round((first_stats['total_correct'] / first_stats['total_questions']) * 100, 2) if first_stats['total_questions'] > 0 else 0
        
        # Promedio de preguntas por usuario - optimizado
        user_questions_all = Result.objects.filter(
            user_id__in=active_users,
            status='completed'
        ).values('user_id').annotate(
            total=Sum(F('correct_answers') + F('wrong_answers'))
        ).aggregate(avg=Avg('total'))
        
        user_questions_first = Result.objects.filter(
            user_id__in=active_users,
            status='completed',
            id=Subquery(first_attempt_subquery)
        ).values('user_id').annotate(
            total=Sum(F('correct_answers') + F('wrong_answers'))
        ).aggregate(avg=Avg('total'))
        
        # Obtener estadísticas por nivel
        level_stats = self.get_community_level_stats_optimized(active_users)
        
        return {
            'all_attempts': {
                'avg_time_taken_per_question': avg_time_all,
                'avg_accuracy': avg_accuracy_all,
                'avg_questions_per_user': round(user_questions_all['avg'] or 0, 2)
            },
            'first_attempt': {
                'avg_time_taken_per_question': avg_time_first,
                'avg_accuracy': avg_accuracy_first,
                'avg_questions_per_user': round(user_questions_first['avg'] or 0, 2)
            },
            'levels': level_stats
        }
    
    def get_community_level_stats_optimized(self, active_users):
        """Obtiene estadísticas de comunidad por nivel - OPTIMIZADO"""
        
        level_stats = {}
        
        for level in PREDEFINED_LEVELS:
            # Subquery para primeros intentos en este nivel
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                test__level=level,
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            
            # Todos los intentos en este nivel
            all_stats = Result.objects.filter(
                user_id__in=active_users,
                status='completed',
                test__level=level
            ).aggregate(
                total_time=Coalesce(Sum('time_taken'), Value(0)),
                total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0)),
                total_correct=Coalesce(Sum('correct_answers'), Value(0))
            )
            
            # Primeros intentos en este nivel
            first_stats = Result.objects.filter(
                user_id__in=active_users,
                status='completed',
                test__level=level,
                id=Subquery(first_attempt_subquery)
            ).aggregate(
                total_time=Coalesce(Sum('time_taken'), Value(0)),
                total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0)),
                total_correct=Coalesce(Sum('correct_answers'), Value(0))
            )
            
            # Calcular promedios
            avg_time_all = round(all_stats['total_time'] / all_stats['total_questions'], 2) if all_stats['total_questions'] > 0 else 0
            avg_time_first = round(first_stats['total_time'] / first_stats['total_questions'], 2) if first_stats['total_questions'] > 0 else 0
            
            avg_accuracy_all = round((all_stats['total_correct'] / all_stats['total_questions']) * 100, 2) if all_stats['total_questions'] > 0 else 0
            avg_accuracy_first = round((first_stats['total_correct'] / first_stats['total_questions']) * 100, 2) if first_stats['total_questions'] > 0 else 0
            
            # Promedio de preguntas por usuario
            user_questions_all = Result.objects.filter(
                user_id__in=active_users,
                status='completed',
                test__level=level
            ).values('user_id').annotate(
                total=Sum(F('correct_answers') + F('wrong_answers'))
            ).aggregate(avg=Avg('total'))
            
            user_questions_first = Result.objects.filter(
                user_id__in=active_users,
                status='completed',
                test__level=level,
                id=Subquery(first_attempt_subquery)
            ).values('user_id').annotate(
                total=Sum(F('correct_answers') + F('wrong_answers'))
            ).aggregate(avg=Avg('total'))
            
            level_stats[level] = {
                'all_attempts': {
                    'avg_time_taken_per_question': avg_time_all,
                    'avg_accuracy': avg_accuracy_all,
                    'avg_questions_per_user': round(user_questions_all['avg'] or 0, 2)
                },
                'first_attempt': {
                    'avg_time_taken_per_question': avg_time_first,
                    'avg_accuracy': avg_accuracy_first,
                    'avg_questions_per_user': round(user_questions_first['avg'] or 0, 2)
                }
            }
        
        return level_stats
    
    def _get_empty_averages(self):
        """Retorna estructura vacía para promedios"""
        empty = {'avg_time_taken_per_question': 0, 'avg_accuracy': 0, 'avg_questions_per_user': 0}
        levels_empty = {level: {'all_attempts': empty.copy(), 'first_attempt': empty.copy()} 
                       for level in PREDEFINED_LEVELS}
        return {
            'all_attempts': empty.copy(),
            'first_attempt': empty.copy(),
            'levels': levels_empty
        }
    
    def get_ranking_position_by_metric(self, user_id, metric_type, attempt_type='all', level=None):
        """Obtiene la posición del usuario en una métrica específica - OPTIMIZADO"""
        
        if metric_type == METRIC_TESTS_COUNT:
            return self._get_position_tests_count(user_id)
        elif metric_type == METRIC_AVG_TIME:
            return self._get_position_avg_time_optimized(user_id, attempt_type)
        elif metric_type == METRIC_ACCURACY:
            return self._get_position_accuracy_optimized(user_id, attempt_type)
        elif metric_type == METRIC_QUESTIONS_ANSWERED:
            return self._get_position_questions_answered_optimized(user_id, attempt_type)
        elif metric_type == 'level_accuracy' and level:
            return self._get_position_level_accuracy_optimized(user_id, level)
        
        return 0
    
    def _get_position_tests_count(self, user_id):
        """Obtiene posición por cantidad de tests"""
        user_tests = Result.objects.filter(
            user_id=user_id,
            status='completed'
        ).values('test_id').distinct().count()
        
        if user_tests == 0:
            return 0
        
        higher_count = Result.objects.filter(
            status='completed'
        ).values('user_id').annotate(
            test_count=Count('test_id', distinct=True)
        ).filter(test_count__gt=user_tests).count()
        
        return higher_count + 1
    
    def _get_position_avg_time_optimized(self, user_id, attempt_type):
        """Obtiene posición por tiempo promedio - OPTIMIZADO"""
        
        query = Result.objects.filter(status='completed')
        
        if attempt_type == 'first':
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            query = query.filter(id=Subquery(first_attempt_subquery))
        
        # Obtener promedio del usuario
        user_avg = query.filter(user_id=user_id).values('user_id').annotate(
            total_time=Sum('time_taken'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(total_questions__gt=0).annotate(
            avg_time=F('total_time') * 1.0 / F('total_questions')
        ).first()
        
        if not user_avg or user_avg['avg_time'] is None:
            return 0
        
        # Contar usuarios con menor promedio (mejor tiempo)
        lower_count = query.values('user_id').annotate(
            total_time=Sum('time_taken'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(
            total_questions__gt=0
        ).annotate(
            avg_time=F('total_time') * 1.0 / F('total_questions')
        ).filter(
            avg_time__lt=user_avg['avg_time'],
            avg_time__isnull=False
        ).count()
        
        return lower_count + 1
    
    def _get_position_accuracy_optimized(self, user_id, attempt_type):
        """Obtiene posición por precisión - OPTIMIZADO"""
        
        query = Result.objects.filter(status='completed')
        
        if attempt_type == 'first':
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            query = query.filter(id=Subquery(first_attempt_subquery))
        
        # Obtener precisión del usuario
        user_acc = query.filter(user_id=user_id).values('user_id').annotate(
            total_correct=Sum('correct_answers'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(total_questions__gt=0).annotate(
            accuracy=F('total_correct') * 100.0 / F('total_questions')
        ).first()
        
        if not user_acc or user_acc['accuracy'] is None:
            return 0
        
        # Contar usuarios con mayor precisión
        higher_count = query.values('user_id').annotate(
            total_correct=Sum('correct_answers'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(
            total_questions__gt=0
        ).annotate(
            accuracy=F('total_correct') * 100.0 / F('total_questions')
        ).filter(
            accuracy__gt=user_acc['accuracy'],
            accuracy__isnull=False
        ).count()
        
        return higher_count + 1
    
    def _get_position_questions_answered_optimized(self, user_id, attempt_type):
        """Obtiene posición por preguntas respondidas - OPTIMIZADO"""
        
        query = Result.objects.filter(status='completed')
        
        if attempt_type == 'first':
            first_attempt_subquery = Result.objects.filter(
                status='completed',
                user_id=OuterRef('user_id'),
                test_id=OuterRef('test_id')
            ).order_by('updated_at').values('id')[:1]
            query = query.filter(id=Subquery(first_attempt_subquery))
        
        user_questions = query.filter(user_id=user_id).aggregate(
            total=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0))
        )['total']
        
        if user_questions == 0:
            return 0
        
        higher_count = query.values('user_id').annotate(
            total=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0))
        ).filter(total__gt=user_questions).count()
        
        return higher_count + 1
    
    def _get_position_level_accuracy_optimized(self, user_id, level):
        """Obtiene posición por precisión por nivel - OPTIMIZADO"""
        
        # Subquery para primer intento del usuario en este nivel
        user_first_attempt_subquery = Result.objects.filter(
            user_id=user_id,
            status='completed',
            test__level=level,
            #user_id=OuterRef('user_id'),
            test_id=OuterRef('test_id')
        ).order_by('updated_at').values('id')[:1]
        
        user_stats = Result.objects.filter(
            user_id=user_id,
            status='completed',
            test__level=level,
            id=Subquery(user_first_attempt_subquery)
        ).aggregate(
            total_correct=Coalesce(Sum('correct_answers'), Value(0)),
            total_questions=Coalesce(Sum(F('correct_answers') + F('wrong_answers')), Value(0))
        )
        
        if not user_stats['total_questions'] or user_stats['total_questions'] == 0:
            return 0
        
        user_accuracy = (user_stats['total_correct'] / user_stats['total_questions']) * 100
        
        # Subquery para primeros intentos de todos los usuarios
        all_first_attempt_subquery = Result.objects.filter(
            status='completed',
            test__level=level,
            user_id=OuterRef('user_id'),
            test_id=OuterRef('test_id')
        ).order_by('updated_at').values('id')[:1]
        
        # Contar usuarios con mayor precisión
        higher_count = Result.objects.filter(
            status='completed',
            test__level=level,
            id=Subquery(all_first_attempt_subquery)
        ).values('user_id').annotate(
            total_correct=Sum('correct_answers'),
            total_questions=Sum(F('correct_answers') + F('wrong_answers'))
        ).filter(
            total_questions__gt=0
        ).annotate(
            accuracy=F('total_correct') * 100.0 / F('total_questions')
        ).filter(
            accuracy__gt=user_accuracy
        ).count()
        
        return higher_count + 1
    
    def get_user_all_ranking_positions(self, user_id):
        """Obtiene todas las posiciones del usuario en una sola llamada - OPTIMIZADO"""
        
        positions = {
            'completed_tests': 0,
            'all_attempts': {
                'avg_time_taken_per_question': 0,
                'accuracy': 0,
                'questions_answered': 0
            },
            'first_attempt': {
                'avg_time_taken_per_question': 0,
                'accuracy': 0,
                'questions_answered': 0
            },
            'levels': {},
            'total_active_users': 0
        }
        
        # Posición en tests completados
        positions['completed_tests'] = self._get_position_tests_count(user_id)
        
        # Posiciones para todos los intentos
        positions['all_attempts']['avg_time_taken_per_question'] = self._get_position_avg_time_optimized(user_id, 'all')
        positions['all_attempts']['accuracy'] = self._get_position_accuracy_optimized(user_id, 'all')
        positions['all_attempts']['questions_answered'] = self._get_position_questions_answered_optimized(user_id, 'all')
        
        # Posiciones para primeros intentos
        positions['first_attempt']['avg_time_taken_per_question'] = self._get_position_avg_time_optimized(user_id, 'first')
        positions['first_attempt']['accuracy'] = self._get_position_accuracy_optimized(user_id, 'first')
        positions['first_attempt']['questions_answered'] = self._get_position_questions_answered_optimized(user_id, 'first')
        
        # Posiciones por nivel
        for level in PREDEFINED_LEVELS:
            positions['levels'][level] = {
                'first_attempt': self._get_position_level_accuracy_optimized(user_id, level)
            }
        
        # Total de usuarios activos
        positions['total_active_users'] = self.get_active_users_count()
        
        return positions