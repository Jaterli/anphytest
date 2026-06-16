# apps/shared/management/commands/populate_test_results.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.accounts.models import User
from apps.test.models import Test
from apps.results.models import Result
from datetime import datetime, timedelta
from django.db import models
import random
import logging
from faker import Faker

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURACIÓN GENERAL - MODIFICAR AQUÍ
# ============================================

CONFIG = {
    'users': 20,
    'use_existing_users': False,
    'max_users_to_use': 50,
    'skip_users': False,
    'clear_existing_users': True,

    'tests_per_user': 5,
    'max_tests_per_user': 15,
    'specific_test_id': None,
    'test_ids': None,

    'correct_percentage_min': 30,
    'correct_percentage_max': 90,
    'completed_percentage': 60,
    'abandoned_percentage': 20,
    'in_progress_percentage': 20,

    'start_date': None,
    'end_date': None,
    'days_back': 720,

    'time_per_question_min': 10,
    'time_per_question_max': 45,

    'clear_existing_results': True,
    'seed': 42,
    'verbose': False,
}

# ============================================

# Argumentos booleanos (action='store_true') — siempre tienen valor, incluso cuando
# no se pasan en CLI (su default es False). Los listamos aquí para tratarlos distinto
# al fusionar con CONFIG.
BOOL_ARGS = {
    'use_existing_users',
    'skip_users',
    'clear_existing_users',
    'clear_existing_results',
    'verbose',
}


class Command(BaseCommand):
    help = 'Rellena tests existentes con resultados y usuarios'

    def add_arguments(self, parser):
        parser.add_argument('--users', type=int)
        parser.add_argument('--use-existing-users', action='store_true', default=None)
        parser.add_argument('--max-users-to-use', type=int)
        parser.add_argument('--skip-users', action='store_true', default=None)
        parser.add_argument('--clear-existing-users', action='store_true', default=None)
        parser.add_argument('--tests-per-user', type=int)
        parser.add_argument('--max-tests-per-user', type=int)
        parser.add_argument('--specific-test-id', type=int)
        parser.add_argument('--test-ids', type=str)
        parser.add_argument('--correct-percentage-min', type=float)
        parser.add_argument('--correct-percentage-max', type=float)
        parser.add_argument('--completed-percentage', type=float)
        parser.add_argument('--abandoned-percentage', type=float)
        parser.add_argument('--in-progress-percentage', type=float)
        parser.add_argument('--start-date', type=str)
        parser.add_argument('--end-date', type=str)
        parser.add_argument('--days-back', type=int)
        parser.add_argument('--time-per-question-min', type=int)
        parser.add_argument('--time-per-question-max', type=int)
        parser.add_argument('--clear-existing-results', action='store_true', default=None)
        parser.add_argument('--seed', type=int)
        parser.add_argument('--verbose', action='store_true', default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake = None
        self.users = []
        self.tests = []
        self.results_created = 0
        self.date_range = None
        self.stats = {'completed': 0, 'abandoned': 0, 'in_progress': 0, 'total': 0}

    def handle(self, *args, **options):
        options = self._merge_config_with_options(options)

        random.seed(options['seed'])
        self.fake = Faker()
        self.fake.seed_instance(options['seed'])

        self.stdout.write(self.style.SUCCESS('🎯 Iniciando población de tests existentes'))
        self.stdout.write(f'📊 Semilla: {options["seed"]}')

        self.date_range = self._calculate_date_range(options)
        self._display_date_range()

        total_percentage = (
            options['completed_percentage']
            + options['abandoned_percentage']
            + options['in_progress_percentage']
        )
        if abs(total_percentage - 100) > 0.01:
            self.stdout.write(self.style.WARNING(
                f'⚠️  Los porcentajes suman {total_percentage}%, ajustando para que sumen 100%'
            ))
            factor = 100 / total_percentage
            options['completed_percentage'] *= factor
            options['abandoned_percentage'] *= factor
            options['in_progress_percentage'] *= factor

        if options['clear_existing_users']:
            self.clear_existing_users()

        self.get_users(options)
        if not self.users:
            self.stdout.write(self.style.ERROR('❌ No hay usuarios disponibles'))
            return

        self.get_tests(options)
        if not self.tests:
            self.stdout.write(self.style.ERROR('❌ No hay tests disponibles'))
            return

        if options['clear_existing_results']:
            self.clear_existing_results()

        self.generate_results(options)
        self.show_statistics(options)

        self.stdout.write(self.style.SUCCESS('✅ Población de tests completada exitosamente'))

    # ------------------------------------------------------------------
    # BUG FIX 1: fusión correcta de CONFIG con argumentos CLI
    # ------------------------------------------------------------------
    # Problema anterior: los argumentos booleanos (store_true) tienen siempre un valor
    # (False cuando no se pasan), así que la condición `value is not None` era siempre
    # True, y sobreescribían el True del CONFIG con False silenciosamente.
    #
    # Solución: para argumentos booleanos, solo sobreescribir CONFIG cuando el usuario
    # los pasó explícitamente en CLI (True). Si no los pasó (False/None), dejar CONFIG.
    # ------------------------------------------------------------------
    def _merge_config_with_options(self, options):
        merged = CONFIG.copy()

        for key, value in options.items():
            if key not in merged:
                continue

            if key in BOOL_ARGS:
                # Solo sobreescribir si el usuario activó el flag explícitamente
                if value is True:
                    merged[key] = True
                # Si es False o None, el valor de CONFIG se mantiene intacto
            else:
                if value is not None:
                    merged[key] = value

        return merged

    # ------------------------------------------------------------------
    # BUG FIX 2: fechas aware vs naive
    # ------------------------------------------------------------------
    # Problema anterior: cuando se usaban --start-date/--end-date, se creaban
    # datetimes naive (sin timezone). Combinados con timezone.now() (aware) en
    # la comparación `min_start = max(start_date, test.created_at)` esto lanzaba
    # un TypeError o producía comparaciones incorrectas con USE_TZ=True.
    #
    # Solución: convertir siempre las fechas específicas a datetimes aware usando
    # timezone.make_aware(), igual que el resultado de timezone.now().
    # ------------------------------------------------------------------
    def _calculate_date_range(self, options):
        if options.get('start_date') and options.get('end_date'):
            try:
                start_naive = datetime.strptime(options['start_date'], '%Y-%m-%d')
                end_naive = datetime.strptime(options['end_date'], '%Y-%m-%d')

                # Convertir a aware con la timezone activa del proyecto
                start_date = timezone.make_aware(
                    datetime.combine(start_naive, datetime.min.time())
                )
                end_date = timezone.make_aware(
                    datetime.combine(end_naive, datetime.max.time())
                )

                if start_date > end_date:
                    self.stdout.write(self.style.WARNING(
                        '⚠️  Fecha de inicio posterior a la de fin — intercambiando'
                    ))
                    start_date, end_date = end_date, start_date

                return {
                    'start': start_date,
                    'end': end_date,
                    'type': 'specific',
                    'days': (end_date - start_date).days,
                }
            except ValueError as e:
                self.stdout.write(self.style.ERROR(f'❌ Error en formato de fecha: {e}'))
                self.stdout.write(self.style.WARNING('⚠️  Usando rango por defecto (days_back)'))

        end_date = timezone.now()
        start_date = end_date - timedelta(days=options['days_back'])
        return {
            'start': start_date,
            'end': end_date,
            'type': 'days_back',
            'days': options['days_back'],
        }

    def _display_date_range(self):
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS('📅 RANGO DE FECHAS CONFIGURADO'))
        self.stdout.write('=' * 60)
        label = 'Fechas específicas' if self.date_range['type'] == 'specific' else 'Días hacia atrás'
        self.stdout.write(f'   Tipo: {label}')
        self.stdout.write(f'   Inicio: {self.date_range["start"].strftime("%Y-%m-%d %H:%M")}')
        self.stdout.write(f'   Fin:    {self.date_range["end"].strftime("%Y-%m-%d %H:%M")}')
        self.stdout.write(f'   Duración: {self.date_range["days"]} días')
        self.stdout.write('=' * 60 + '\n')

    # ------------------------------------------------------------------
    # BUG FIX 3: clear_existing_users ignoraba usuarios con otros prefijos
    # ------------------------------------------------------------------
    # No había bug de lógica aquí, pero el método dependía de que BUG FIX 1
    # estuviera resuelto para que 'clear_existing_users': True del CONFIG
    # no fuera sobreescrito a False por el argumento CLI no pasado.
    # ------------------------------------------------------------------
    def clear_existing_users(self):
        self.stdout.write('🗑️  Eliminando usuarios existentes...')
        users_to_delete = User.objects.filter(username__startswith='test_user_')
        count = users_to_delete.count()
        if count > 0:
            users_to_delete.delete()
            self.stdout.write(self.style.SUCCESS(f'   Eliminados {count} usuarios'))
        else:
            self.stdout.write('   No se encontraron usuarios para eliminar')

    # ------------------------------------------------------------------
    # MEJORA: bulk_create para usuarios — mucho más rápido con N grande
    # ------------------------------------------------------------------
    def get_users(self, options):
        if options['use_existing_users'] or options['skip_users']:
            qs = User.objects.filter(is_active=True)
            if options['max_users_to_use']:
                qs = qs[:options['max_users_to_use']]
            self.users = list(qs)
            self.stdout.write(self.style.SUCCESS(f'👥 Usando {len(self.users)} usuarios existentes'))
            return

        self.stdout.write(f'👥 Creando {options["users"]} usuarios...')

        existing_usernames = set(User.objects.values_list('username', flat=True))
        start_date = self.date_range['start']
        end_date = self.date_range['end']
        date_range_seconds = int((end_date - start_date).total_seconds())

        users_to_create = []
        user_counter = 1
        target = options['users']

        while len(users_to_create) < target:
            username = f'test_user_{user_counter}'
            if username not in existing_usernames:
                random_seconds = random.randint(0, date_range_seconds) if date_range_seconds > 0 else 0
                registered_at = start_date + timedelta(seconds=random_seconds)

                # Construimos el objeto sin guardarlo todavía
                user = User(
                    username=username,
                    email=f'{username}@example.com',
                    first_name=self.fake.first_name(),
                    last_name=self.fake.last_name(),
                    role='user',
                    is_active=True,
                    registered_at=registered_at,
                )
                user.set_password('test123')
                users_to_create.append(user)

            user_counter += 1

        # Un solo INSERT en bloque en lugar de N INSERTs individuales.
        # Nota: bulk_create no garantiza que los objetos devueltos tengan pk asignado
        # en todas las versiones de Django/BD, así que recargamos desde BD por username.
        usernames = [u.username for u in users_to_create]
        User.objects.bulk_create(users_to_create, ignore_conflicts=True)
        self.users = list(User.objects.filter(username__in=usernames))
        self.stdout.write(self.style.SUCCESS(f'   Total usuarios creados: {len(self.users)}'))

    def get_tests(self, options):
        self.stdout.write('📝 Obteniendo tests...')
        qs = (
            Test.objects.filter(is_active=True)
            .annotate(num_questions=models.Count('questions'))
            .filter(num_questions__gt=0)
        )
        if options['specific_test_id']:
            qs = qs.filter(id=options['specific_test_id'])
        if options['test_ids']:
            ids = [int(i.strip()) for i in options['test_ids'].split(',')]
            qs = qs.filter(id__in=ids)

        # Precargar preguntas y respuestas en una sola query cada una
        self.tests = list(qs.prefetch_related('questions__answers'))

        if not self.tests:
            self.stdout.write(self.style.WARNING('⚠️  No se encontraron tests con preguntas'))
            return

        self.stdout.write(self.style.SUCCESS(f'   Total tests disponibles: {len(self.tests)}'))
        if options['verbose']:
            for test in self.tests[:5]:
                self.stdout.write(f'      - {test.title} (ID: {test.id}, Preguntas: {test.num_questions})')
            if len(self.tests) > 5:
                self.stdout.write(f'      ... y {len(self.tests) - 5} más')

    def clear_existing_results(self):
        self.stdout.write('🗑️  Limpiando resultados existentes...')
        test_ids = [t.id for t in self.tests]
        deleted_count = Result.objects.filter(test_id__in=test_ids).delete()[0]
        self.stdout.write(self.style.SUCCESS(f'   Eliminados {deleted_count} resultados'))

    # ------------------------------------------------------------------
    # MEJORA: bulk_create para resultados — un INSERT en lugar de N
    # ------------------------------------------------------------------
    def generate_results(self, options):
        self.stdout.write('📊 Generando resultados...')

        completed_pct = options['completed_percentage'] / 100
        abandoned_pct = options['abandoned_percentage'] / 100
        correct_min = options['correct_percentage_min'] / 100
        correct_max = options['correct_percentage_max'] / 100

        start_date = self.date_range['start']
        end_date = self.date_range['end']

        results_to_create = []

        for user_idx, user in enumerate(self.users):
            num_tests = random.randint(
                options['tests_per_user'],
                min(options['max_tests_per_user'], len(self.tests)),
            )
            selected_tests = random.sample(self.tests, min(num_tests, len(self.tests)))

            for test in selected_tests:
                # Las preguntas ya están precargadas — sin query adicional
                questions = list(test.questions.all())
                if not questions:
                    continue

                rand = random.random()
                if rand < completed_pct:
                    status = 'completed'
                elif rand < completed_pct + abandoned_pct:
                    status = 'abandoned'
                else:
                    status = 'in_progress'

                if status == 'completed':
                    num_answered = len(questions)
                elif status == 'abandoned':
                    min_a = max(1, int(len(questions) * 0.2))
                    max_a = max(min_a + 1, int(len(questions) * 0.6))
                    num_answered = random.randint(min_a, min(max_a, len(questions)))
                else:
                    min_a = max(1, int(len(questions) * 0.1))
                    max_a = max(min_a + 1, int(len(questions) * 0.5))
                    num_answered = random.randint(min_a, min(max_a, len(questions) - 1))

                answered_questions = random.sample(questions, num_answered)
                target_correct_pct = random.uniform(correct_min, correct_max)

                answers_dict = {}
                correct_count = 0
                wrong_count = 0

                for question in answered_questions:
                    # Las respuestas también están precargadas
                    answers = list(question.answers.all())
                    if not answers:
                        continue

                    if random.random() < target_correct_pct:
                        pool = [a for a in answers if a.is_correct] or answers
                    else:
                        pool = [a for a in answers if not a.is_correct] or answers

                    selected_answer = random.choice(pool)
                    answers_dict[str(question.id)] = selected_answer.id

                    if selected_answer.is_correct:
                        correct_count += 1
                    else:
                        wrong_count += 1

                time_per_question = random.randint(
                    options['time_per_question_min'],
                    options['time_per_question_max'],
                )
                time_taken = num_answered * time_per_question

                # test.created_at es aware (auto_now_add con USE_TZ=True)
                min_start = max(start_date, test.created_at)
                max_start = end_date

                if min_start < max_start:
                    time_range = int((max_start - min_start).total_seconds())
                    started_at = min_start + timedelta(seconds=random.randint(0, time_range) if time_range > 0 else 0)
                else:
                    started_at = test.created_at + timedelta(hours=1)

                if status in ('in_progress', 'abandoned'):
                    actual_time = int(time_taken * random.uniform(0.2, 0.8))
                    updated_at = started_at + timedelta(seconds=actual_time)
                else:
                    updated_at = started_at + timedelta(seconds=time_taken)

                if updated_at > end_date:
                    updated_at = end_date
                    if updated_at < started_at:
                        started_at = updated_at - timedelta(seconds=min(time_taken, 60))

                results_to_create.append(Result(
                    user=user,
                    test=test,
                    correct_answers=correct_count,
                    wrong_answers=wrong_count,
                    time_taken=time_taken,
                    status=status,
                    answers=answers_dict,
                    started_at=started_at,
                    updated_at=updated_at,
                ))

                self.stats[status] += 1
                self.stats['total'] += 1

            if (user_idx + 1) % 5 == 0:
                self.stdout.write(f'   ✓ Procesados {user_idx + 1}/{len(self.users)} usuarios')

        # Un solo INSERT en bloque
        Result.objects.bulk_create(results_to_create, ignore_conflicts=True)
        self.results_created = len(results_to_create)

        self.stdout.write(self.style.SUCCESS(
            f'   Resultados creados: {self.results_created} '
            f'(Completados: {self.stats["completed"]}, '
            f'Abandonados: {self.stats["abandoned"]}, '
            f'En progreso: {self.stats["in_progress"]})'
        ))

    def show_statistics(self, options):
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS('📈 ESTADÍSTICAS FINALES'))
        self.stdout.write('=' * 60)

        self.stdout.write(f'\n📝 Tests procesados: {len(self.tests)}')
        if self.tests:
            total_questions = sum(t.num_questions for t in self.tests)
            avg_questions = total_questions / len(self.tests)
            self.stdout.write(f'   - Preguntas totales: {total_questions}')
            self.stdout.write(f'   - Promedio preguntas/test: {avg_questions:.1f}')

        self.stdout.write(f'\n👥 Usuarios utilizados: {len(self.users)}')

        self.stdout.write(f'\n📅 Rango de fechas aplicado:')
        self.stdout.write(f'   - Inicio: {self.date_range["start"].strftime("%Y-%m-%d %H:%M:%S")}')
        self.stdout.write(f'   - Fin:    {self.date_range["end"].strftime("%Y-%m-%d %H:%M:%S")}')
        self.stdout.write(f'   - Duración: {self.date_range["days"]} días')

        if self.results_created > 0:
            self.stdout.write(f'\n📊 Resultados creados: {self.results_created}')
            for key, label in (('completed', 'Completados'), ('abandoned', 'Abandonados'), ('in_progress', 'En progreso')):
                pct = self.stats[key] / self.results_created * 100
                self.stdout.write(f'   - {label}: {self.stats[key]} ({pct:.1f}%)')

            test_ids = [t.id for t in self.tests]
            completed_qs = Result.objects.filter(test_id__in=test_ids, status='completed')
            if completed_qs.exists():
                # Calcular score promedio en una sola query en lugar de iterar
                from django.db.models import F, ExpressionWrapper, FloatField, Sum
                total_correct = completed_qs.aggregate(s=Sum('correct_answers'))['s'] or 0
                total_answered = completed_qs.aggregate(
                    s=Sum(models.F('correct_answers') + models.F('wrong_answers'))
                )['s'] or 0
                avg_score = (total_correct / total_answered * 100) if total_answered else 0
                self.stdout.write(f'   - Score promedio (completados): {avg_score:.1f}%')

            self.stdout.write(f'\n📅 Consistencia de fechas (muestra):')
            for r in Result.objects.filter(test_id__in=test_ids)[:3]:
                diff = (r.updated_at - r.started_at).total_seconds()
                if abs(diff - r.time_taken) <= 1:
                    self.stdout.write(self.style.SUCCESS(f'   ✅ {r.status}: {diff:.0f}s ≈ {r.time_taken}s'))
                else:
                    self.stdout.write(self.style.WARNING(f'   ⚠️  {r.status}: {diff:.0f}s ≠ {r.time_taken}s'))

            self.stdout.write(f'\n🏆 Tests más populares:')
            top = (
                Result.objects.filter(test_id__in=test_ids)
                .values('test_id', 'test__title')
                .annotate(count=models.Count('id'))
                .order_by('-count')[:5]
            )
            for t in top:
                self.stdout.write(f'   - {t["test__title"]}: {t["count"]} intentos')

        self.stdout.write('\n' + '=' * 60)