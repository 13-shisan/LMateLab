#!/usr/bin/env bash
set -e
celery -A celery_app.celery_app beat -l INFO