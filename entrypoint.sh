#!/bin/bash
set -e

echo "=== NoteSphere Backend Entrypoint ==="

# Required environment variables check
required_vars=(
  SECRET_KEY
  ALLOWED_HOSTS
  DEBUG
  API_DOCS_ENABLED
  AUTH_ATTEMPT_WINDOW_SECONDS
  AUTH_LOCKOUT_SECONDS
  LOGIN_MAX_ATTEMPTS_PER_EMAIL
  LOGIN_MAX_ATTEMPTS_PER_IP
  FRONTEND_URL
  PASSWORD_RESET_TOKEN_LIFETIME
  DEFAULT_FROM_EMAIL
  PASSWORD_RESET_MAX_REQUESTS
  PASSWORD_RESET_MAX_REQUESTS_PER_IP
  NUM_PROXIES
  MONGODB_URI
)

for var in "${required_vars[@]}"; do
  if [ -z "${!var}" ]; then
    echo "ERROR: Required environment variable $var is not set."
    exit 1
  fi
done

# Wait for MongoDB to be ready
echo "Waiting for MongoDB at ${MONGODB_URI}..."
until python -c "
import pymongo, os, sys
try:
    client = pymongo.MongoClient(os.environ['MONGODB_URI'], serverSelectionTimeoutMS=3000)
    client.admin.command('ping')
    sys.exit(0)
except Exception as e:
    print(f'MongoDB not ready: {e}')
    sys.exit(1)
"; do
  echo "MongoDB unavailable - retrying in 2s..."
  sleep 2
done
echo "MongoDB is ready."

# Run database migrations
echo "Running Django migrations..."
python manage.py migrate --noinput --settings=configs.settings

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput --settings=configs.settings

# Start Gunicorn
echo "Starting Gunicorn on 0.0.0.0:${PORT:-8000}..."
exec gunicorn configs.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${WEB_CONCURRENCY:-3} \
  --threads 2 \
  --worker-tmp-dir /dev/shm \
  --access-logfile - \
  --error-logfile -