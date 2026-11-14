"""Create the initial admin from ADMIN_* environment variables if missing."""

import os

from django.core.management.base import BaseCommand

from api.admin import create_user
from api.models import USERS_COLLECTION, ROLE_ADMIN
from db_connection import get_collection


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Command(BaseCommand):
    help = "Creates the initial admin user from .env if one does not already exist."

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME")
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")

        if not (username and email and password):
            self.stdout.write(self.style.WARNING(
                "ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD সেট করা নেই; এডমিন তৈরি করা হবে না।"
            ))
            return

        users = get_collection(USERS_COLLECTION)

        # ইউজারনাম বা ইমেইল যেকোনো একটিতে যদি থাকে, তবে নতুন তৈরি করবে না
        existing = users.find_one({
            "$or": [
                {"username": username.lower()},
                {"email": email.lower()},
            ]
        }, {"_id": 1})
        if existing:
            self.stdout.write(self.style.NOTICE(
                f"এডমিন ইতিমধ্যে আছে ({username}); তৈরি করা হচ্ছে না।"
            ))
            return

        data = {
            "username": username,
            "email": email,
            "password": password,
            "full_name": os.getenv("ADMIN_FULL_NAME", "System Admin"),
            "role": os.getenv("ADMIN_ROLE", ROLE_ADMIN),
            "is_active": _truthy(os.getenv("ADMIN_IS_ACTIVE", "true")),
            "is_verified": _truthy(os.getenv("ADMIN_IS_VERIFIED", "true")),
        }

        try:
            user = create_user(data)
            self.stdout.write(self.style.SUCCESS(
                f"প্রাথমিক এডমিন তৈরি করা হলো: {user['username']} ({user['email']})"
            ))
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f"এডমিন তৈরি করতে সমস্যা হয়েছে: {exc}"
            ))