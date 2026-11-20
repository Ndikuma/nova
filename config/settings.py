from pathlib import Path
import os
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path):
    """Charge .env sans dépendance externe (les variables déjà définies gagnent)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[7:]
        key, value = line.split('=', 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env(BASE_DIR / '.env')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','apps.core','apps.workspaces','apps.hotel','apps.restaurant','apps.bar','apps.inventory','apps.finance','apps.reports','apps.obr_ebms']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','apps.core.context_processors.navigation']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        # Take the write lock before a posting reads the balance it will update.
        'OPTIONS': {'transaction_mode': 'IMMEDIATE'},
    },
}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = 'fr-fr'; TIME_ZONE = 'Africa/Abidjan'; USE_I18N = True; USE_TZ = True
STATIC_URL = 'static/'; STATIC_ROOT = BASE_DIR/'staticfiles'; STATICFILES_DIRS = [BASE_DIR/'static']
MEDIA_URL = 'media/'; MEDIA_ROOT = BASE_DIR/'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'; AUTH_USER_MODEL = 'core.User'

# Profil de l'établissement — géré dans la base (apps.core.models.CompanyProfile).
# Devise de repli (utilisée si le profil n'est pas encore configuré/migré).
NOVA_CURRENCY = os.getenv('NOVA_CURRENCY', 'BIF')
NOVA_CURRENCY_SYMBOL = os.getenv('NOVA_CURRENCY_SYMBOL', 'FBu')

LOGIN_URL = '/login/'; LOGIN_REDIRECT_URL = '/'; LOGOUT_REDIRECT_URL = '/login/'
