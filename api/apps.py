from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    verbose_name = "NoteSphere API"

    def ready(self):
        # সার্ভার চালু হওয়ার সময় .env থেকে এডমিন তৈরি করুন (যদি না থাকে)
        import os
        if os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD"):
            from django.core.management import call_command
            try:
                call_command("create_initial_admin")
            except Exception:
                # সার্ভার ক্র্যাশ না করে এডমিন তৈরি না পারলে চুপচাপ এগিয়ে যান
                pass