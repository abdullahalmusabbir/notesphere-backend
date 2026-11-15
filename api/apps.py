from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    verbose_name = "NoteSphere API"

    def ready(self):
        import os
        if os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD"):
            from django.core.management import call_command
            try:
                call_command("create_initial_admin")
            except Exception:
                pass