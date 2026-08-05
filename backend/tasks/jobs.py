# backend/tasks/jobs.py
import logging
from celery_app import celery_app
from tasks.dailypapers import run_daily_digest, JOURNAL_FEEDS

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.jobs.daily_digest_all")
def daily_digest_all():
    # 跑所有配置了 feed 的期刊；单个期刊失败不影响其他
    ok, fail = 0, 0

    for journal in JOURNAL_FEEDS.keys():
        try:
            run_daily_digest(journal)
            ok += 1
        except Exception as e:
            fail += 1
            logger.exception("[daily_digest_all] journal=%s failed: %s", journal, e)
            continue

    logger.info("[daily_digest_all] finished: ok=%s fail=%s", ok, fail)
