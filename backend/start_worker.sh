#!/usr/bin/env bash
# backend/start_worker.sh
set -e
celery -A celery_app.celery_app worker -l INFO --concurrency 4
