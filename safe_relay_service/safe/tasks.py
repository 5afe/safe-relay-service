from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings

logger = get_task_logger(__name__)


"""
@app.shared_task(bind=True,
                 default_retry_delay=settings.NOTIFICATION_RETRY_DELAY_SECONDS,
                 max_retries=settings.NOTIFICATION_MAX_RETRIES)
def testing_task(self, message: str, push_token: str) -> None:
    try:
        return None
    except Exception as exc:
        logger.error(exc, exc_info=True)
        logger.info('Retry sending message with push_token=%s' % push_token)
        self.retry(exc=exc)
"""
