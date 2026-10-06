from pathlib import Path
import os, secrets
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.')
    keyfile = BASE_DIR / '.local-secret'
    if not keyfile.exists():
        keyfile.write_text(secrets.token_urlsafe(64), encoding='utf-8')
    SECRET_KEY = keyfile.read_text(encoding='utf-8')
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
INSTALLED_APPS = ['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','rental']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','rental.views.role_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
# IMMEDIATE serialises writers before availability is read. Triggers provide an
# independent constraint even when a caller bypasses the service layer.
DATABASES = {'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('RENTAL_DB',str(BASE_DIR/'db.sqlite3')),'OPTIONS':{'timeout':20,'transaction_mode':'IMMEDIATE'},'TEST':{'NAME':str(BASE_DIR/'test.sqlite3')}}}
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE='en-gb'
TIME_ZONE='Africa/Lagos'
USE_I18N=True
USE_TZ=True
STATIC_URL='/static/'
STATICFILES_DIRS=[BASE_DIR/'static']
STATIC_ROOT=BASE_DIR/'staticfiles'
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
LOGIN_URL='/login/'
LOGIN_REDIRECT_URL='/'
LOGOUT_REDIRECT_URL='/login/'
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
SESSION_COOKIE_AGE=3600
SESSION_COOKIE_SECURE=not DEBUG
CSRF_COOKIE_SECURE=not DEBUG
SECURE_SSL_REDIRECT=not DEBUG
SECURE_HSTS_SECONDS=31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS=not DEBUG
SECURE_HSTS_PRELOAD=not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF=True
X_FRAME_OPTIONS='DENY'
