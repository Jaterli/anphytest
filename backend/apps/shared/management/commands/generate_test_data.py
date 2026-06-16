# apps/shared/management/commands/generate_test_data.py

# Genera tets, preguntas, respuestas, usuarios, etc

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from apps.accounts.models import User
from apps.test.models import Test
from apps.results.models import Result
from apps.shared.models import get_topics
from datetime import datetime, timedelta
import random
import logging
from faker import Faker #type: ignore
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)

class ResultStatus(Enum):
    COMPLETED = 'completed'
    ABANDONED = 'abandoned'
    IN_PROGRESS = 'in_progress'

@dataclass
class RangeConfig:
    """Configuración para rangos de valores"""
    min: float
    max: float
    
    def get_random(self) -> float:
        """Obtiene un valor aleatorio dentro del rango"""
        if isinstance(self.min, int) and isinstance(self.max, int):
            return random.randint(self.min, self.max)
        return random.uniform(self.min, self.max)
    
    def get_random_int(self) -> int:
        """Obtiene un entero aleatorio dentro del rango"""
        return random.randint(int(self.min), int(self.max))

class Command(BaseCommand):
    help = 'Genera datos de prueba para tests, usuarios y resultados'
    
    # ==================== CONFIGURACIÓN CENTRALIZADA ====================
    CONFIG = {
        # Configuración de usuarios
        'USERS_COUNT': 15,
        'ADMIN_PERCENTAGE': 0.1,
        'GUEST_PERCENTAGE': 0.2,
        
        # Rangos configurables (min, max)
        'RANGES': {
            'QUESTIONS_PER_TEST': RangeConfig(10, 20),      # Entre 10 y 20 preguntas por test
            'RESULTS_PER_USER': RangeConfig(5, 15),        # Entre 5 y 15 resultados por usuario
            'CORRECT_ANSWERS_PERCENTAGE': RangeConfig(0.4, 0.95),  # Entre 40% y 95% de aciertos
            'TIME_PER_QUESTION': RangeConfig(15, 60),      # Segundos por pregunta
        },
        
        # Configuración de tests
        'TESTS_PER_TOPIC': 2,
        'ANSWERS_PER_QUESTION': 4,
        
        # Configuración de fechas
        'TEST_START_DATE': '2024-01-01',
        'TEST_END_DATE': '2026-05-30',
        
        # Configuración de resultados
        'INCOMPLETE_PERCENTAGE': 0.15,
        'ABANDONED_PERCENTAGE': 0.10,
        
        # Flags de control
        'CLEAR_EXISTING': False,
        'SKIP_USERS': False,
        'SEED': 42,
        'MAX_USERS_TO_PROCESS': 20,
        'VERBOSE': True,
        'USE_EXISTING_TESTS': True,
        'BATCH_SIZE': 100,  # Tamaño de lote para operaciones masivas
    }
    # ====================================================================
    
    # Templates precompilados para generar contenido
    QUESTION_TEMPLATES = [
        "¿Cuál es el concepto fundamental de {specific}?",
        "Explique cómo funciona {specific} en el contexto de {main}",
        "¿Cuál de las siguientes afirmaciones sobre {specific} es correcta?",
        "En {sub}, ¿qué relación tiene {specific} con otros conceptos?",
        "¿Qué herramienta/método se utiliza para resolver problemas de {specific}?",
        "¿Cuál es el error más común al aprender {specific}?",
        "¿Cómo se aplica {specific} en casos prácticos de {main}?",
        "¿Qué característica distingue a {specific} de otros temas similares?",
        "¿Cuál es el resultado esperado al aplicar {specific} correctamente?",
        "¿Qué requisitos previos son necesarios para entender {specific}?"
    ]
    
    CORRECT_ANSWER_TEMPLATES = [
        "La respuesta correcta es esta opción por las siguientes razones...",
        "Esta es la definición estándar según la literatura del tema.",
        "Correcto. Esta opción describe exactamente el concepto.",
        "Sí, esta es la respuesta correcta que cumple con todos los criterios.",
        "Así es. Esta es la solución más apropiada en este contexto."
    ]
    
    INCORRECT_ANSWER_TEMPLATES = [
        "Esta es una confusión común pero incorrecta.",
        "No, esta opción no refleja correctamente el concepto.",
        "Esta respuesta sería válida en otro contexto pero no aquí.",
        "Cuidado: esta es una falacia frecuente en este tema.",
        "Incorrecto. Revisa la definición básica del concepto."
    ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake = None
        self.topics = []
        self.created_users = []
        self.created_tests = []
        self.config = self.CONFIG.copy()
        self.stats = {
            'users_created': 0,
            'tests_created': 0,
            'questions_created': 0,
            'answers_created': 0,
            'results_created': 0,
            'completed': 0,
            'abandoned': 0,
            'in_progress': 0
        }
        
    def add_arguments(self, parser):
        """Argumentos CLI que sobrescriben la configuración"""
        parser.add_argument('--users', type=int, help='Número de usuarios a crear')
        parser.add_argument('--admin-percentage', type=float, help='Porcentaje de admins')
        parser.add_argument('--guest-percentage', type=float, help='Porcentaje de invitados')
        parser.add_argument('--tests-per-topic', type=int, help='Tests por tema')
        parser.add_argument('--questions-min', type=int, help='Mínimo preguntas por test')
        parser.add_argument('--questions-max', type=int, help='Máximo preguntas por test')
        parser.add_argument('--answers-per-question', type=int, help='Respuestas por pregunta')
        parser.add_argument('--results-min', type=int, help='Mínimo resultados por usuario')
        parser.add_argument('--results-max', type=int, help='Máximo resultados por usuario')
        parser.add_argument('--correct-min', type=float, help='Mínimo % aciertos (0-1)')
        parser.add_argument('--correct-max', type=float, help='Máximo % aciertos (0-1)')
        parser.add_argument('--test-start-date', type=str, help='Fecha inicio tests')
        parser.add_argument('--test-end-date', type=str, help='Fecha fin tests')
        parser.add_argument('--incomplete-percentage', type=float, help='% tests incompletos')
        parser.add_argument('--abandoned-percentage', type=float, help='% tests abandonados')
        parser.add_argument('--clear-existing', action='store_true', help='Limpiar datos existentes')
        parser.add_argument('--skip-users', action='store_true', help='Saltar creación de usuarios')
        parser.add_argument('--seed', type=int, help='Semilla para reproducibilidad')
        parser.add_argument('--max-users', type=int, help='Máximo usuarios a procesar')
        parser.add_argument('--no-verbose', action='store_true', help='Modo silencioso')
        
    def handle(self, *args, **options):
        """Método principal de ejecución"""
        self.apply_config(options)
        self.setup_random_generators()
        
        self.print_header()
        self.show_current_config()
        
        with transaction.atomic():
            self.clear_data_if_requested()
            self.create_or_load_users()
            self.load_topics()
            self.create_tests()
            self.create_questions_and_answers()
            self.create_results()
        
        self.show_statistics()
        self.print_footer()
    
    def setup_random_generators(self):
        """Configura los generadores aleatorios"""
        random.seed(self.config['SEED'])
        self.fake = Faker()
        self.fake.seed_instance(self.config['SEED'])
    
    def apply_config(self, options):
        """Aplica configuración desde CLI"""
        # Mapeo directo de parámetros simples
        simple_mappings = {
            'users': 'USERS_COUNT',
            'admin_percentage': 'ADMIN_PERCENTAGE',
            'guest_percentage': 'GUEST_PERCENTAGE',
            'tests_per_topic': 'TESTS_PER_TOPIC',
            'answers_per_question': 'ANSWERS_PER_QUESTION',
            'test_start_date': 'TEST_START_DATE',
            'test_end_date': 'TEST_END_DATE',
            'incomplete_percentage': 'INCOMPLETE_PERCENTAGE',
            'abandoned_percentage': 'ABANDONED_PERCENTAGE',
            'clear_existing': 'CLEAR_EXISTING',
            'skip_users': 'SKIP_USERS',
            'seed': 'SEED',
            'max_users': 'MAX_USERS_TO_PROCESS'
        }
        
        for cli_arg, config_key in simple_mappings.items():
            if options.get(cli_arg) is not None:
                self.config[config_key] = options[cli_arg]
        
        # Configuración de rangos
        if options.get('questions_min') is not None or options.get('questions_max') is not None:
            q_min = options.get('questions_min', self.config['RANGES']['QUESTIONS_PER_TEST'].min)
            q_max = options.get('questions_max', self.config['RANGES']['QUESTIONS_PER_TEST'].max)
            self.config['RANGES']['QUESTIONS_PER_TEST'] = RangeConfig(q_min, q_max)
        
        if options.get('results_min') is not None or options.get('results_max') is not None:
            r_min = options.get('results_min', self.config['RANGES']['RESULTS_PER_USER'].min)
            r_max = options.get('results_max', self.config['RANGES']['RESULTS_PER_USER'].max)
            self.config['RANGES']['RESULTS_PER_USER'] = RangeConfig(r_min, r_max)
        
        if options.get('correct_min') is not None or options.get('correct_max') is not None:
            c_min = options.get('correct_min', self.config['RANGES']['CORRECT_ANSWERS_PERCENTAGE'].min)
            c_max = options.get('correct_max', self.config['RANGES']['CORRECT_ANSWERS_PERCENTAGE'].max)
            self.config['RANGES']['CORRECT_ANSWERS_PERCENTAGE'] = RangeConfig(c_min, c_max)
        
        if options.get('no_verbose'):
            self.config['VERBOSE'] = False
    
    def print_header(self):
        """Imprime cabecera"""
        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('🚀 GENERADOR DE DATOS DE PRUEBA'))
        self.stdout.write(self.style.SUCCESS('='*70))
    
    def print_footer(self):
        """Imprime pie"""
        self.stdout.write(self.style.SUCCESS('\n✨ ¡Generación completada exitosamente! ✨'))
        self.stdout.write(self.style.SUCCESS('='*70 + '\n'))
    
    def show_current_config(self):
        """Muestra la configuración actual de forma más legible"""
        if not self.config['VERBOSE']:
            return
            
        ranges = self.config['RANGES']
        
        self.stdout.write('\n📋 CONFIGURACIÓN ACTIVA:')
        self.stdout.write(f'   👥 Usuarios: {self.config["USERS_COUNT"]} '
                         f'(Admin: {self.config["ADMIN_PERCENTAGE"]*100:.0f}%, '
                         f'Guest: {self.config["GUEST_PERCENTAGE"]*100:.0f}%)')
        
        self.stdout.write(f'   📝 Tests: {self.config["TESTS_PER_TOPIC"]} por tema, '
                         f'{ranges["QUESTIONS_PER_TEST"].min}-{ranges["QUESTIONS_PER_TEST"].max} preguntas/test, '
                         f'{self.config["ANSWERS_PER_QUESTION"]} respuestas/pregunta')
        
        self.stdout.write(f'   📊 Resultados: {ranges["RESULTS_PER_USER"].min}-{ranges["RESULTS_PER_USER"].max} por usuario, '
                         f'Aciertos: {ranges["CORRECT_ANSWERS_PERCENTAGE"].min*100:.0f}%-{ranges["CORRECT_ANSWERS_PERCENTAGE"].max*100:.0f}%')
        
        self.stdout.write(f'   ⏱️  Tiempo/pregunta: {ranges["TIME_PER_QUESTION"].min}-{ranges["TIME_PER_QUESTION"].max}s')
        self.stdout.write(f'   🎲 Semilla: {self.config["SEED"]}\n')
    
    def clear_data_if_requested(self):
        """Limpia datos si está configurado"""
        if not self.config['CLEAR_EXISTING']:
            return
            
        self.stdout.write('🗑️  Limpiando datos existentes...')
        
        # Borrar en orden correcto por FK
        Result.objects.all().delete()
        Answer.objects.all().delete()
        Question.objects.all().delete()
        Test.objects.all().delete()
        
        if not self.config['SKIP_USERS'] and self.config['VERBOSE']:
            confirm = input('¿Eliminar usuarios existentes? (s/n): ').lower() == 's'
            if confirm:
                User.objects.exclude(is_superuser=True).delete()
                self.stdout.write('   ✅ Usuarios eliminados')
            else:
                self.stdout.write('   📌 Usuarios conservados')
    
    def create_or_load_users(self):
        """Crea o carga usuarios eficientemente"""
        if self.config['SKIP_USERS']:
            self.created_users = list(User.objects.filter(is_active=True))
            self.stdout.write(self.style.SUCCESS(f'📌 Usando {len(self.created_users)} usuarios existentes'))
            return
        
        self.stdout.write(f'👥 Creando {self.config["USERS_COUNT"]} usuarios...')
        
        num_admins = int(self.config['USERS_COUNT'] * self.config['ADMIN_PERCENTAGE'])
        num_guests = int(self.config['USERS_COUNT'] * self.config['GUEST_PERCENTAGE'])
        num_regular = self.config['USERS_COUNT'] - num_admins - num_guests
        
        # Crear usuarios por tipo
        self._create_users_by_role('admin', num_admins, 'admin_', 'admin123', is_staff=True)
        self._create_users_by_role('guest', num_guests, 'guest_', 'guest123')
        self._create_users_by_role('user', num_regular, 'user_', 'user123')
        
        # Completar con usuarios existentes si es necesario
        if len(self.created_users) < self.config['USERS_COUNT']:
            needed = self.config['USERS_COUNT'] - len(self.created_users)
            existing = User.objects.exclude(id__in=[u.id for u in self.created_users]).filter(is_active=True)[:needed]
            self.created_users.extend(existing)
            self.stdout.write(self.style.WARNING(f'   ⚠️  Usando {len(existing)} usuarios existentes'))
        
        self.stats['users_created'] = len(self.created_users)
        self.stdout.write(self.style.SUCCESS(f'   ✅ Total: {len(self.created_users)} usuarios disponibles'))
    
    def _create_users_by_role(self, role: str, count: int, prefix: str, password: str, is_staff: bool = False):
        """Crea usuarios de un rol específico"""
        created = 0
        counter = 1
        
        while created < count and counter < 100:
            username = f"{prefix}{counter}"
            email = f"{username}@example.com"
            
            if not User.objects.filter(username=username).exists():
                try:
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=self.fake.first_name(),
                        last_name=self.fake.last_name(),
                        role=role,
                        is_staff=is_staff,
                        is_active=True
                    )
                    self.created_users.append(user)
                    created += 1
                    
                    if self.config['VERBOSE'] and created % 10 == 0:
                        self.stdout.write(f'   ✓ Creados {created} {role}s')
                except Exception as e:
                    if self.config['VERBOSE']:
                        self.stdout.write(self.style.WARNING(f'   Error: {e}'))
            counter += 1
    
    def load_topics(self):
        """Carga temas de forma optimizada"""
        self.stdout.write('📚 Cargando temas...')
        
        topics_data = get_topics(include_predefined=True, force_refresh=True)
        
        # Aplanar jerarquía usando list comprehension
        self.topics = [
            {
                'main': main_topic['name'],
                'sub': sub_topic['name'],
                'specific': specific_topic
            }
            for main_topic in topics_data
            for sub_topic in main_topic['sub_topics']
            for specific_topic in sub_topic['specific_topics']
        ]
        
        self.stdout.write(self.style.SUCCESS(f'   ✅ {len(self.topics)} temas encontrados'))
        
        if self.config['VERBOSE'] and self.topics:
            self.stdout.write('   📖 Ejemplos:')
            for topic in self.topics[:2]:
                self.stdout.write(f'      • {topic["main"]} → {topic["sub"]} → {topic["specific"]}')
    
    def create_tests(self):
        """Crea tests de forma optimizada"""
        if not self.topics:
            self.stdout.write(self.style.WARNING('   ⚠️  No hay temas para crear tests'))
            return
            
        self.stdout.write('📝 Creando tests...')
        
        start_date = datetime.strptime(self.config['TEST_START_DATE'], '%Y-%m-%d')
        end_date = datetime.strptime(self.config['TEST_END_DATE'], '%Y-%m-%d')
        date_range_days = (end_date - start_date).days
        
        admins = [u for u in self.created_users if u.role == 'admin'] or self.created_users
        
        tests_to_create = []
        levels = ['Principiante', 'Intermedio', 'Avanzado']
        
        for topic in self.topics:
            for i in range(self.config['TESTS_PER_TOPIC']):
                level = levels[i % len(levels)]
                title = f"{topic['specific']} - Nivel {level}"
                
                if self.config['USE_EXISTING_TESTS']:
                    existing = Test.objects.filter(title=title, main_topic=topic['main']).first()
                    if existing:
                        self.created_tests.append(existing)
                        continue
                
                # Preparar test para creación masiva
                random_days = random.randint(0, max(1, date_range_days))
                created_at = start_date + timedelta(days=random_days)
                
                tests_to_create.append(Test(
                    title=title,
                    description=self.fake.paragraph(nb_sentences=3),
                    main_topic=topic['main'],
                    sub_topic=topic['sub'],
                    specific_topic=topic['specific'],
                    level=level,
                    created_by=random.choice(admins),
                    created_at=created_at,
                    updated_at=created_at,
                    is_active=True
                ))
        
        # Creación masiva de tests
        if tests_to_create:
            self.created_tests.extend(Test.objects.bulk_create(tests_to_create, batch_size=self.config['BATCH_SIZE']))
        
        self.stats['tests_created'] = len(self.created_tests)
        self.stdout.write(self.style.SUCCESS(f'   ✅ {len(self.created_tests)} tests disponibles'))
    
    def create_questions_and_answers(self):
        """Crea preguntas y respuestas de forma eficiente usando bulk_create"""
        if not self.created_tests:
            self.stdout.write(self.style.WARNING('   ⚠️  No hay tests para crear contenido'))
            return
            
        self.stdout.write('❓ Generando preguntas y respuestas...')
        
        questions_to_create = []
        answers_to_create = []
        answers_per_question = self.config['ANSWERS_PER_QUESTION']
        
        # Pre-calcular rangos de preguntas por test
        questions_range = self.config['RANGES']['QUESTIONS_PER_TEST']
        
        for test in self.created_tests:
            if test.questions.exists():
                continue
                
            num_questions = questions_range.get_random_int()
            
            # Crear preguntas para este test
            for q_num in range(num_questions):
                question_text = self._generate_question_text(test)
                questions_to_create.append(Question(test=test, question_text=question_text))
        
        # Bulk create preguntas
        if questions_to_create:
            created_questions = Question.objects.bulk_create(questions_to_create, batch_size=self.config['BATCH_SIZE'])
            self.stats['questions_created'] = len(created_questions)
            
            # Crear respuestas para cada pregunta
            for question in created_questions:
                correct_index = random.randint(0, answers_per_question - 1)
                
                for a_num in range(answers_per_question):
                    is_correct = (a_num == correct_index)
                    answer_text = self._generate_answer_text(is_correct)
                    answers_to_create.append(Answer(
                        question=question,
                        answer_text=answer_text,
                        is_correct=is_correct
                    ))
            
            # Bulk create respuestas
            if answers_to_create:
                Answer.objects.bulk_create(answers_to_create, batch_size=self.config['BATCH_SIZE'])
                self.stats['answers_created'] = len(answers_to_create)
        
        self.stdout.write(self.style.SUCCESS(
            f'   ✅ {self.stats["questions_created"]} preguntas, '
            f'{self.stats["answers_created"]} respuestas creadas'
        ))
    
    def _generate_question_text(self, test: Test) -> str:
        """Genera texto de pregunta usando templates"""
        template = random.choice(self.QUESTION_TEMPLATES)
        return template.format(
            specific=test.specific_topic,
            main=test.main_topic,
            sub=test.sub_topic
        )
    
    def _generate_answer_text(self, is_correct: bool) -> str:
        """Genera texto de respuesta usando templates"""
        templates = self.CORRECT_ANSWER_TEMPLATES if is_correct else self.INCORRECT_ANSWER_TEMPLATES
        return random.choice(templates)
    
    def create_results(self):
        """Crea resultados con control preciso de aciertos"""
        if not self.created_users or not self.created_tests:
            self.stdout.write(self.style.WARNING('   ⚠️  No hay usuarios o tests para crear resultados'))
            return
            
        self.stdout.write('📊 Generando resultados...')
        
        results_per_user_range = self.config['RANGES']['RESULTS_PER_USER']
        correct_range = self.config['RANGES']['CORRECT_ANSWERS_PERCENTAGE']
        time_range = self.config['RANGES']['TIME_PER_QUESTION']
        
        # Probabilidades de estado
        probs = {
            ResultStatus.COMPLETED: 1 - self.config['INCOMPLETE_PERCENTAGE'] - self.config['ABANDONED_PERCENTAGE'],
            ResultStatus.ABANDONED: self.config['ABANDONED_PERCENTAGE'],
            ResultStatus.IN_PROGRESS: self.config['INCOMPLETE_PERCENTAGE']
        }
        
        max_users = min(self.config['MAX_USERS_TO_PROCESS'], len(self.created_users))
        
        for user_idx, user in enumerate(self.created_users[:max_users]):
            num_results = results_per_user_range.get_random_int()
            selected_tests = random.sample(
                self.created_tests,
                min(num_results, len(self.created_tests))
            )
            
            for test in selected_tests:
                self._create_single_result(user, test, probs, correct_range, time_range)
            
            if self.config['VERBOSE'] and (user_idx + 1) % 5 == 0:
                self.stdout.write(f'   ✓ Procesados {user_idx + 1}/{max_users} usuarios')
        
        self.stdout.write(self.style.SUCCESS(
            f'   ✅ {self.stats["results_created"]} resultados '
            f'(✓{self.stats["completed"]} | ⊘{self.stats["abandoned"]} | ⋯{self.stats["in_progress"]})'
        ))
    
    def _create_single_result(self, user: User, test: Test, probs: Dict, correct_range: RangeConfig, time_range: RangeConfig):
        """Crea un resultado individual"""
        questions = list(test.questions.all())
        if not questions:
            return
        
        # Determinar estado
        status = random.choices(
            list(probs.keys()),
            weights=list(probs.values())
        )[0]
        
        # Determinar número de preguntas respondidas
        if status == ResultStatus.COMPLETED:
            num_answered = len(questions)
        elif status == ResultStatus.ABANDONED:
            num_answered = random.randint(1, max(1, len(questions) // 2))
        else:  # IN_PROGRESS
            num_answered = random.randint(1, max(1, len(questions) - 1))
        
        # Seleccionar preguntas a responder
        answered_questions = random.sample(questions, num_answered)
        
        # Generar respuestas
        answers_dict = {}
        correct_count = 0
        
        if status == ResultStatus.COMPLETED:
            # Para tests completados, controlar porcentaje de aciertos
            target_correct_percentage = correct_range.get_random()
            target_correct = int(num_answered * target_correct_percentage)
            target_correct = max(1, min(target_correct, num_answered)) if target_correct_percentage > 0 else 0
            
            # Mezclar preguntas para distribución aleatoria de aciertos
            shuffled_questions = answered_questions.copy()
            random.shuffle(shuffled_questions)
            
            for idx, question in enumerate(shuffled_questions):
                should_be_correct = idx < target_correct
                selected_answer = self._select_answer_for_question(question, should_be_correct)
                
                if selected_answer:
                    answers_dict[str(question.id)] = selected_answer.id
                    if selected_answer.is_correct:
                        correct_count += 1
        else:
            # Para tests no completados, selección aleatoria
            for question in answered_questions:
                answers = list(question.answers.all())
                if answers:
                    selected_answer = random.choice(answers)
                    answers_dict[str(question.id)] = selected_answer.id
                    if selected_answer.is_correct:
                        correct_count += 1
        
        wrong_count = num_answered - correct_count
        time_taken = num_answered * time_range.get_random_int()
        
        # Fecha de inicio (posterior a creación del test)
        started_at = self._generate_start_date(test)
        
        # Crear resultado
        try:
            with transaction.atomic():
                Result.objects.create(
                    user=user,
                    test=test,
                    correct_answers=correct_count,
                    wrong_answers=wrong_count,
                    time_taken=int(time_taken),
                    status=status.value,
                    answers=answers_dict,
                    started_at=started_at,
                    updated_at=started_at + timedelta(seconds=time_taken) if status == ResultStatus.COMPLETED else started_at
                )
                self.stats['results_created'] += 1
                
                if status == ResultStatus.COMPLETED:
                    self.stats['completed'] += 1
                elif status == ResultStatus.ABANDONED:
                    self.stats['abandoned'] += 1
                else:
                    self.stats['in_progress'] += 1
        except Exception as e:
            if self.config['VERBOSE']:
                self.stdout.write(self.style.WARNING(f'   Error: {e}'))
    
    def _select_answer_for_question(self, question: Question, want_correct: bool) -> Optional[Answer]:
        """Selecciona una respuesta según si se quiere correcta o no"""
        answers = list(question.answers.all())
        if not answers:
            return None
        
        if want_correct:
            correct_answers = [a for a in answers if a.is_correct]
            return random.choice(correct_answers) if correct_answers else random.choice(answers)
        else:
            incorrect_answers = [a for a in answers if not a.is_correct]
            return random.choice(incorrect_answers) if incorrect_answers else random.choice(answers)
    
    def _generate_start_date(self, test: Test) -> datetime:
        """Genera fecha de inicio aleatoria posterior a la creación del test"""
        min_start = test.created_at
        max_start = timezone.now() if test.created_at < timezone.now() else test.created_at + timedelta(days=1)
        
        if min_start >= max_start:
            return min_start
        
        random_seconds = random.randint(0, int((max_start - min_start).total_seconds()))
        return min_start + timedelta(seconds=random_seconds)
    
    def show_statistics(self):
        """Muestra estadísticas detalladas"""
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('📈 ESTADÍSTICAS FINALES'))
        self.stdout.write('='*70)
        
        # Estadísticas de la base de datos
        db_stats = {
            'users': User.objects.count(),
            'admins': User.objects.filter(role='admin').count(),
            'guests': User.objects.filter(role='guest').count(),
            'regular': User.objects.filter(role='user').count(),
            'tests': Test.objects.count(),
            'active_tests': Test.objects.filter(is_active=True).count(),
            'questions': Question.objects.count(),
            'answers': Answer.objects.count(),
            'results': Result.objects.count(),
            'completed': Result.objects.filter(status='completed').count(),
            'abandoned': Result.objects.filter(status='abandoned').count(),
            'in_progress': Result.objects.filter(status='in_progress').count(),
        }
        
        # Mostrar estadísticas formateadas
        self.stdout.write(f'\n👥 USUARIOS: {db_stats["users"]}')
        self.stdout.write(f'   ├─ Administradores: {db_stats["admins"]}')
        self.stdout.write(f'   ├─ Invitados: {db_stats["guests"]}')
        self.stdout.write(f'   └─ Regulares: {db_stats["regular"]}')
        
        self.stdout.write(f'\n📝 TESTS: {db_stats["tests"]}')
        self.stdout.write(f'   ├─ Activos: {db_stats["active_tests"]}')
        
        if db_stats["tests"] > 0:
            for level in ['Principiante', 'Intermedio', 'Avanzado']:
                count = Test.objects.filter(level=level).count()
                self.stdout.write(f'   ├─ {level}: {count}')
        
        self.stdout.write(f'\n❓ CONTENIDO:')
        self.stdout.write(f'   ├─ Preguntas: {db_stats["questions"]}')
        self.stdout.write(f'   └─ Respuestas: {db_stats["answers"]}')
        
        if db_stats["questions"] > 0:
            self.stdout.write(f'   └─ Promedio respuestas/pregunta: {db_stats["answers"]/db_stats["questions"]:.1f}')
        
        if db_stats["results"] > 0:
            completed_pct = db_stats["completed"] / db_stats["results"] * 100
            abandoned_pct = db_stats["abandoned"] / db_stats["results"] * 100
            progress_pct = db_stats["in_progress"] / db_stats["results"] * 100
            
            self.stdout.write(f'\n📊 RESULTADOS: {db_stats["results"]}')
            self.stdout.write(f'   ├─ Completados: {db_stats["completed"]} ({completed_pct:.1f}%)')
            self.stdout.write(f'   ├─ Abandonados: {db_stats["abandoned"]} ({abandoned_pct:.1f}%)')
            self.stdout.write(f'   └─ En progreso: {db_stats["in_progress"]} ({progress_pct:.1f}%)')
            
            # Calcular score promedio
            completed_results = Result.objects.filter(status='completed')
            if completed_results.exists():
                total_score = sum(r.score_percentage for r in completed_results)
                avg_score = total_score / completed_results.count()
                self.stdout.write(f'\n   🎯 Score promedio (completados): {avg_score:.1f}%')
                self.stdout.write(f'   🎲 Rango configurado: {self.config["RANGES"]["CORRECT_ANSWERS_PERCENTAGE"].min*100:.0f}%-{self.config["RANGES"]["CORRECT_ANSWERS_PERCENTAGE"].max*100:.0f}%')
        
        self.stdout.write('\n' + '='*70)