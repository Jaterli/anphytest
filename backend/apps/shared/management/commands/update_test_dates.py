# apps/shared/management/commands/update_test_dates.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.timezone import make_aware
from apps.test.models import Test
from datetime import datetime, timedelta
import random

class Command(BaseCommand):
    help = 'Actualiza las fechas de creación de tests a fechas aleatorias'
    
    def add_arguments(self, parser):
        parser.add_argument('--start-date', type=str, default='2024-01-01', 
                           help='Fecha inicio (YYYY-MM-DD)')
        parser.add_argument('--end-date', type=str, default='2026-05-30', 
                           help='Fecha fin (YYYY-MM-DD)')
        parser.add_argument('--dry-run', action='store_true', 
                           help='Mostrar cambios sin aplicarlos')
        parser.add_argument('--seed', type=int, default=42, 
                           help='Semilla para reproducibilidad')
    
    def handle(self, *args, **options):
        random.seed(options['seed'])
        
        start_date = datetime.strptime(options['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(options['end_date'], '%Y-%m-%d')
        days_diff = (end_date - start_date).days
        
        # Hacer las fechas "aware" (con zona horaria)
        start_date = make_aware(start_date)
        end_date = make_aware(end_date)
        
        tests = Test.objects.all()
        self.stdout.write(f'📝 Actualizando {tests.count()} tests...')
        
        updated_count = 0
        for test in tests:
            # Generar fecha aleatoria
            random_days = random.randint(0, days_diff)
            random_seconds = random.randint(0, 86399)  # Segundos en un día
            new_date = start_date + timedelta(days=random_days, seconds=random_seconds)
            
            if not options['dry_run']:
                test.created_at = new_date
                test.updated_at = new_date
                test.save(update_fields=['created_at', 'updated_at'])
            
            updated_count += 1
            
            if updated_count % 50 == 0:
                self.stdout.write(f'   Procesados {updated_count} tests...')
        
        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'✅ Simulación completada: {updated_count} tests actualizarían'))
        else:
            self.stdout.write(self.style.SUCCESS(f'✅ Actualizados {updated_count} tests'))