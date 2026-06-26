# AnGoTest - Plataforma de Tests Online con Angular y Django

![Angular](https://img.shields.io/badge/Angular-20+-red?logo=angular)
![Django](https://img.shields.io/badge/Django-5.2+-darkgreen?logo=django)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue?logo=postgresql)
![TailwindCSS](https://img.shields.io/badge/TailwindCSS-3+-blue?logo=tailwindcss)
![License](https://img.shields.io/badge/License-MIT-green)

**AnGoTest** es una plataforma web completa para la creación, gestión y realización de tests online. Esta versión representa la evolución del proyecto, migrando el backend a **Django** para aprovechar sus potentes herramientas y acelerar el desarrollo, mientras se mantiene un frontend moderno y eficiente con **Angular**.

> 🚀 **Proyecto final de Máster en Desarrollo Web Full Stack**

---

## 👨‍🏫 Guía para el Evaluador

Para facilitar la evaluación completa de todas las funcionalidades de la aplicación, se han creado los siguientes datos de prueba:

### 🔑 Credenciales de Administrador (superusuario de Django)

| Campo | Valor |
|-------|-------|
| **Email** | `admin@angotest.com` |
| **Contraseña** | `13113013@WfX` |

### 🔑 Credenciales de usuario

| Campo | Valor |
|-------|-------|
| **Email** | `test_user_n@example.com` *|
| **Contraseña** | `test123` |

\* Sustituir 'n' por el número correspondiente.

### 📚 Datos de Prueba

La base de datos incluye datos de ejemplo precargados para que puedas explorar la aplicación sin necesidad de crearlos manualmente:

- **Tests de ejemplo:** Varios tests completos con preguntas y respuestas en diferentes niveles de dificultad y temáticas.
- **Usuarios de prueba:** Cuentas adicionales con diferentes roles y progreso para visualizar rankings y estadísticas.
- **Resultados históricos:** Datos de tests completados para probar el dashboard y los rankings globales.

### 🎯 Recomendaciones para la Evaluación

1. **Panel de Administración:** Accede al dashboard administrativo para ver KPIs, gestionar usuarios, tests y resultados.
2. **Generación por IA:** Prueba la funcionalidad de generación automática de tests usando la API de Groq.
3. **Rankings:** Verifica los rankings globales y específicos por nivel de dificultad.
4. **Recuperación de contraseña:** Simula el flujo de recuperación para comprobar el envío de emails.
5. **Rol de invitado (Guest):** Crea un test con invitación y prueba el flujo de usuario invitado.
6. **Importación JSON:** Utiliza la estructura documentada para importar tests desde asistentes externos.

---

## ✨ Características Principales

### 👥 Gestión de Usuarios
- Registro, login/logout con JWT en cookies HttpOnly.
- Recuperación de contraseña por email con tokens seguros.
- Tres roles: `user`, `admin` y `guest` (invitado).
- Conversión de cuenta `guest` a usuario permanente.
- Desactivación de cuenta con anonimización completa de datos.

### 📚 Sistema de Tests
- Jerarquía de 3 niveles: **Tema Principal > Subtema > Tema Específico**.
- Niveles de dificultad: **Principiante, Intermedio, Avanzado**.
- Filtrado avanzado por tema, nivel y búsqueda.
- Guardado automático de progreso (tests en curso).
- Historial de tests completados con estadísticas detalladas.
- Visualización de respuestas incorrectas al finalizar.

### 🏆 Rankings y Gamificación
- Rankings globales por:
  - Tests completados.
  - Precisión (primer intento vs. todos los intentos).
  - Tiempo por pregunta.
  - Preguntas respondidas.
- Rankings específicos por nivel de dificultad.
- Posición actual del usuario en cada ranking.
- Promedios de la comunidad para comparativa.

### 🛠️ Panel de Administración
- Dashboard con KPIs y estadísticas en tiempo real.
- CRUD completo de tests con editor visual.
- Gestión de usuarios: ver perfiles, estadísticas, eliminar con transferencia.
- Gestión de resultados: listado, filtros, eliminación individual/masiva.
- Gestión de invitaciones a tests.
- Configuración del sistema mediante clave-valor.

### 🤖 Integración con IA (Groq)
- Generación automática de tests por IA.
- Modo guiado (jerarquía existente) y modo libre (IA infiere la jerarquía).
- Soporte multi-idioma: ES, EN, FR, DE, IT, PT.
- Sistema de cuotas mensuales por usuario (configurable).
- **Importación desde asistentes externos** vía JSON estructurado.

### 📧 Sistema de Invitaciones
- Enlaces únicos para invitar a usuarios a tests específicos.
- Soporte para usuarios invitados (`guest`).
- Transferencia automática de progreso al registrarse.

---

## 🏗️ Arquitectura del Proyecto (Versión Django)

```
AnGoTest/
├── frontend/                 # Aplicación Angular 20+
│   ├── src/app/
│   │   ├── core/            # Servicios, guards, interceptores
│   │   ├── shared/          # Componentes reutilizables
│   │   └── features/        # Módulos funcionales
│   │       ├── auth/        # Autenticación
│   │       ├── dashboard/   # Dashboard usuario
│   │       ├── tests/       # Tests y realización
│   │       ├── results/     # Historial y detalle
│   │       ├── rankings/    # Rankings globales
│   │       └── admin/       # Panel administración
│   └── ...
│
├── backend/                 # API en Django
│   ├── angotest/            # Configuración del proyecto
│   │   ├── settings.py      # Configuración centralizada
│   │   └── urls.py          # Enrutamiento principal
│   └── apps/                # Aplicaciones modulares
│       ├── accounts/        # Autenticación y usuarios
│       ├── admin_panel/     # Administración, cuotas y configuración
│       ├── ai/              # Generación de tests por IA
│       ├── invitations/     # Sistema de invitaciones
│       ├── results/         # Progreso y resultados de tests
│       ├── shared/          # Modelos y lógica compartida (ej. temas)
│       └── test/            # Modelo y gestión de tests
│
└── db/
    ├── migrations/          # Migraciones SQL
    └── seed/                # Datos iniciales
```

---

## 🛠️ Tecnologías Utilizadas

### Backend (Nuevo en Django)
| Tecnología | Versión | Propósito |
|------------|---------|-----------|
| **Django** | 5.2+ | Framework web principal (MTV) |
| **Django REST Framework** | - | API RESTful robusta y flexible |
| **PostgreSQL** | 15+ | Base de datos relacional principal |
| **Simple JWT** | - | Autenticación JWT integrada con DRF |
| **CORS Headers** | - | Gestión de peticiones cross-origin |
| **Redis / LocMem** | - | Sistema de caché para alto rendimiento |

### Frontend
| Tecnología | Versión | Propósito |
|------------|---------|-----------|
| Angular | 20+ | Framework principal |
| TailwindCSS | 3+ | Estilos y diseño |
| Signals | - | Estado reactivo |
| TypeScript | 5+ | Tipado estático |

### Por qué Django es una Elección Superior para este Proyecto

La migración de Go a Django no es solo un cambio técnico, sino una decisión estratégica que aporta enormes beneficios:

- **Productividad Exponencial (DRF y ORM):** El ORM de Django y Django REST Framework (DRF) permiten crear APIs complejas en una fracción del tiempo. La lógica de negocio, como los rankings o las estadísticas del dashboard, se implementa con unas pocas líneas de código Python, en lugar de cientos en Go. El `admin` integrado de Django ofrece un panel de gestión gratuito que aceleró el desarrollo y la depuración de datos.

- **Seguridad "Out-of-the-Box":** Django incluye protección contra las vulnerabilidades web más comunes (XSS, CSRF, SQL Injection, Clickjacking) por defecto. Esto proporciona una base mucho más sólida y reduce el riesgo de errores de seguridad críticos que, en Go, requerirían una implementación manual más cuidadosa.

- **Ecosistema y Comunidad Gigantescos:** Django tiene una de las comunidades más grandes y activas del mundo Python. Esto se traduce en miles de paquetes (`apps`) listos para usar (como `django-cors-headers`, `django-otp`, `django-import-export`), una documentación excelente y una gran cantidad de soluciones a problemas comunes.

- **Escalabilidad y Mantenimiento:** La estructura modular de Django (basada en "apps") hace que el código sea mucho más mantenible y escalable. Añadir nuevas funcionalidades es sencillo, ya que se pueden crear nuevas apps que aíslan la lógica. Además, la curva de aprendizaje para nuevos desarrolladores es mucho menor que en Go, facilitando la incorporación de más personas al equipo.

- **Rendimiento con Caché:** La integración nativa de Django con sistemas de caché como Redis, Memcached o incluso la caché en memoria local (`LocMemCache`), permite acelerar drásticamente las consultas más pesadas (como las del dashboard o los rankings) sin necesidad de implementar complejas soluciones de caching desde cero.

---

## 🚀 Instalación y Configuración

### Requisitos Previos
- Python 3.10 o superior
- Node.js 20+ con npm/pnpm
- PostgreSQL 15+
- (Opcional) API Key de Groq para generación IA

### Backend (Django)

```bash
# Clonar el repositorio
git clone https://github.com/tu-usuario/angotest.git
cd angotest/backend

# Crear y activar un entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Copiar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales (DB, JWT, etc.)

# Ejecutar migraciones
python manage.py migrate

# Iniciar servidor de desarrollo
python manage.py runserver
# Servidor en http://localhost:8000
```

### Frontend

```bash
cd ../frontend

# Instalar dependencias
npm install

# Iniciar servidor de desarrollo
npm start
# Aplicación en http://localhost:4200
```

### Variables de Entorno (Backend)

```env
# Django
DJANGO_SECRET_KEY=tu_secret_key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Base de Datos
DB_NAME=angotest_db
DB_USER=postgres
DB_PASSWORD=tu_password
DB_HOST=localhost
DB_PORT=5432

# JWT y Seguridad
JWT_SECRET=tu_secret_key
ENV=development

# Email (SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu_email
EMAIL_HOST_PASSWORD=tu_password
DEFAULT_FROM_EMAIL=noreply@angotest.com

# IA (Groq)
GROQ_API_KEY=tu_api_key
GROQ_MODEL=llama3-70b-8192
AI_REQUESTS_PER_MONTH=5
```

---

## 📋 Endpoints Principales de la API

### Autenticación
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/api/auth/register` | Registro de usuario |
| POST | `/api/auth/login` | Inicio de sesión |
| POST | `/api/auth/logout` | Cierre de sesión |
| GET | `/api/auth/check-auth` | Verificar autenticación |
| POST | `/api/auth/forgot-password` | Recuperar contraseña |
| POST | `/api/auth/reset-password` | Restablecer contraseña |

### Tests (Usuario)
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/test/<int:test_id>/` | Obtener test con preguntas |
| POST | `/api/test/<int:test_id>/save/` | Guardar progreso |
| GET | `/api/test/not-started/` | Tests no iniciados |
| GET | `/api/test/in-progress/` | Tests en progreso |
| GET | `/api/test/completed/` | Tests completados |
| GET | `/api/test/<int:test_id>/questions/` | Obtener preguntas paginadas |
| GET | `/api/test/<int:test_id>/next-question/` | Siguiente pregunta sin responder |

### Rankings
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/auth/dashboard/rankings` | Rankings globales |

### Administración
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/admin/dashboard/` | Dashboard admin |
| POST | `/api/test/admin/create/` | Crear test |
| PUT | `/api/test/admin/<int:test_id>/edit/` | Editar test |
| DELETE | `/api/test/admin/<int:test_id>/delete/` | Eliminar test |
| GET | `/api/auth/users/stats/` | Listar usuarios con estadísticas |
| DELETE | `/api/auth/users/<int:user_id>/delete/` | Eliminar usuario |

### IA
| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/api/ai-requests/generate-ai-test/` | Generar test con IA |
| GET | `/api/ai-requests/quota/` | Consultar cuota |

---

## 🧪 Ejemplo de Importación JSON desde Asistente IA

Cualquier asistente de IA externo puede generar tests para AnGoTest siguiendo esta estructura:

```json
{
  "title": "El Sistema Solar",
  "description": "Test sobre planetas y características del sistema solar",
  "main_topic": "Astronomía",
  "sub_topic": "Sistema Solar",
  "specific_topic": "Planetas",
  "questions": [
    {
      "question_text": "¿Cuál es el planeta más cercano al Sol?",
      "answers": [
        { "answer_text": "Mercurio", "is_correct": true },
        { "answer_text": "Venus", "is_correct": false },
        { "answer_text": "Tierra", "is_correct": false },
        { "answer_text": "Marte", "is_correct": false }
      ]
    }
  ]
}
```

**Prompt sugerido:**
> *"Genera un test de 10 preguntas sobre [tema] para nivel [principiante/intermedio/avanzado] con 4 opciones cada una, en formato JSON compatible con AnGoTest"*

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit tus cambios (`git commit -m 'Añadir nueva funcionalidad'`)
4. Push a la rama (`git push origin feature/nueva-funcionalidad`)
5. Abre un Pull Request

---

## 📄 Licencia

Este proyecto está bajo la licencia **MIT**. Consulta el archivo [LICENSE](LICENSE) para más detalles.

---

## 📧 Contacto

**Autor:** Jaime TL

- GitHub: [@jaterli](https://github.com/jaterli)
- Email: jaime@angotest.com

---

## 🙏 Agradecimientos

- [Angular](https://angular.dev/) - Framework frontend
- [Django](https://www.djangoproject.com/) - Framework web para Python
- [Django REST Framework](https://www.django-rest-framework.org/) - Toolkit para construir APIs
- [TailwindCSS](https://tailwindcss.com/) - Framework CSS
- [Groq](https://groq.com/) - API de IA para generación de tests

---

⭐ **Si te gusta este proyecto, no olvides darle una estrella en GitHub.**