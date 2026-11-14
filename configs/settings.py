from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ["SECRET_KEY"]

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG")

ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    "api.apps.ApiConfig", 
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
]

ROOT_URLCONF = 'configs.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'configs.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration


# ------------------------------------------------------------------ custom
# API docs toggle (used by configs/urls.py)
API_DOCS_ENABLED = os.environ["API_DOCS_ENABLED"].strip().lower() in ("true", "1", "yes", "on")

# Auth rate limiting & lockout (used by api/docker_services.py)
AUTH_ATTEMPT_WINDOW_SECONDS = int(os.environ["AUTH_ATTEMPT_WINDOW_SECONDS"])
AUTH_LOCKOUT_SECONDS = int(os.environ["AUTH_LOCKOUT_SECONDS"])
LOGIN_MAX_ATTEMPTS_PER_EMAIL = int(os.environ["LOGIN_MAX_ATTEMPTS_PER_EMAIL"])
LOGIN_MAX_ATTEMPTS_PER_IP = int(os.environ["LOGIN_MAX_ATTEMPTS_PER_IP"])

# Password reset (used by api/docker_services.py)
FRONTEND_URL = os.environ["FRONTEND_URL"]
PASSWORD_RESET_TOKEN_LIFETIME = int(os.environ["PASSWORD_RESET_TOKEN_LIFETIME"])
DEFAULT_FROM_EMAIL = os.environ["DEFAULT_FROM_EMAIL"]
PASSWORD_RESET_MAX_REQUESTS = int(os.environ["PASSWORD_RESET_MAX_REQUESTS"])
PASSWORD_RESET_MAX_REQUESTS_PER_IP = int(os.environ["PASSWORD_RESET_MAX_REQUESTS_PER_IP"])

# Trusted proxies for client IP (used by api/views.py)
NUM_PROXIES = int(os.environ["NUM_PROXIES"])

# ------------------------------------------------------------------ CORS
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# The frontend sends Authorization: Bearer <token>, so credentials are required.
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_METHODS = [
    "DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT",
]

CORS_ALLOW_HEADERS = [
    "accept", "accept-encoding", "authorization", "content-type", "dnt",
    "origin", "user-agent", "x-csrftoken", "x-requested-with",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "api.authentications.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}