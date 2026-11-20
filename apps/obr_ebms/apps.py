from django.apps import AppConfig


class ObrEbmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.obr_ebms'
    verbose_name = 'OBR eBMS'

    def ready(self):
        from . import signals  # noqa: F401
