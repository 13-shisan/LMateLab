# backend/celery_app.py
import os
from celery import Celery
from celery.schedules import crontab

broker = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

celery_app = Celery(
    "vasp_scan",
    broker=broker,
    backend=backend,
    include=[
        "tasks.vasp_scan",
        "tasks.vasp_custom_add_all", # 让 worker 启动时注册vasp的批量收藏任务
        "tasks.qe_epw_custom_add_all",   # 让 worker 启动时注册qe_epw的批量收藏任务
        "tasks.jobs", # ✅ 新增：每日导读任务
    ]
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=60 * 30,
    task_soft_time_limit=60 * 25,
    timezone="Asia/Shanghai",
    enable_utc=False,
)

celery_app.conf.beat_schedule = {
    # 每天 08:00 跑
    "daily-digest-all-0800": {
        "task": "tasks.jobs.daily_digest_all",
        "schedule": crontab(hour=8, minute=0),
    },
}
