"""
أدوات مساعدة للتواصل مع بوت التلغرام:
- send_telegram_message: إرسال رسالة نصية (تُستخدم لسجلات عمليات لوحة التحكم)
- send_telegram_document: إرسال ملف (تُستخدم للنسخة الاحتياطية اليومية لقاعدة البيانات)

كل الدوال هنا "صامتة الفشل" عمداً: أي خطأ في الاتصال بتلغرام (لا إنترنت،
توكن خاطئ، chat_id غير مُعرَّف...) لن يُسقط الطلب الأساسي في لوحة التحكم؛
فقط يُسجَّل في الـ logger لمراجعته لاحقاً.
"""
import logging
import os
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger('halaqat.telegram')

TELEGRAM_API_BASE = 'https://api.telegram.org/bot{token}/{method}'
REQUEST_TIMEOUT = 10  # ثوانٍ


def _is_configured():
    return bool(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') and getattr(settings, 'TELEGRAM_CHAT_ID', ''))


def send_telegram_message(text):
    """إرسال رسالة نصية للمحادثة المُعرَّفة في الإعدادات. لا يرفع استثناء عند الفشل."""
    if not _is_configured():
        logger.info('Telegram غير مُهيأ (التوكن أو chat_id فارغ) - تم تجاهل الرسالة: %s', text)
        return False
    try:
        url = TELEGRAM_API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method='sendMessage')
        response = requests.post(
            url,
            data={'chat_id': settings.TELEGRAM_CHAT_ID, 'text': text},
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            logger.warning('فشل إرسال رسالة تلغرام: %s - %s', response.status_code, response.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.warning('خطأ اتصال أثناء إرسال رسالة تلغرام: %s', exc)
        return False


def send_telegram_document(file_path, caption=''):
    """إرسال ملف من القرص (مثل نسخة قاعدة البيانات) للمحادثة المُعرَّفة في الإعدادات."""
    if not _is_configured():
        logger.info('Telegram غير مُهيأ (التوكن أو chat_id فارغ) - تم تجاهل إرسال الملف: %s', file_path)
        return False
    try:
        url = TELEGRAM_API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method='sendDocument')
        with open(file_path, 'rb') as f:
            response = requests.post(
                url,
                data={'chat_id': settings.TELEGRAM_CHAT_ID, 'caption': caption},
                files={'document': f},
                timeout=60,
            )
        if not response.ok:
            logger.warning('فشل إرسال ملف تلغرام: %s - %s', response.status_code, response.text)
            return False
        return True
    except (requests.RequestException, OSError) as exc:
        logger.warning('خطأ أثناء إرسال ملف تلغرام: %s', exc)
        return False


def send_telegram_document_bytes(file_bytes, filename, caption=''):
    """إرسال ملف من الذاكرة مباشرة (bytes) دون الحاجة لحفظه على القرص أولاً.
    مفيد للتقارير المُولَّدة ديناميكياً (مثل تصدير Excel الفوري)."""
    if not _is_configured():
        logger.info('Telegram غير مُهيأ (التوكن أو chat_id فارغ) - تم تجاهل إرسال الملف: %s', filename)
        return False
    try:
        url = TELEGRAM_API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method='sendDocument')
        response = requests.post(
            url,
            data={'chat_id': settings.TELEGRAM_CHAT_ID, 'caption': caption},
            files={'document': (filename, file_bytes)},
            timeout=60,
        )
        if not response.ok:
            logger.warning('فشل إرسال ملف تلغرام: %s - %s', response.status_code, response.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.warning('خطأ أثناء إرسال ملف تلغرام: %s', exc)
        return False


# ══════════════════════════════════════════════════════════════
#  تجميع سجل العمليات: رسالة واحدة مختصرة كل فترة بدل رسالة لكل عملية
#  (يقلّل عدد الطلبات على تلغرام ويجعل السجل مقروءاً)
# ══════════════════════════════════════════════════════════════

BATCH_DELAY = float(os.environ.get('TELEGRAM_BATCH_SECONDS', '120'))   # ثوانٍ
MAX_LINES = 30                     # أقصى عدد سطور في الرسالة الواحدة
_QUEUE = []                        # [(نص السطر، الوقت)]
_GLOCK = threading.Lock()
_GTIMER = [None]


def _flush_queue():
    """يرسل كل ما تجمّع في رسالة واحدة (بلا تكرار لاسم المستخدم/الوقت في كل سطر)."""
    with _GLOCK:
        items = list(_QUEUE)
        _QUEUE.clear()
        _GTIMER[0] = None
    if not items:
        return
    lines = [f'📋 {len(items)} عملية {"(آخر " + str(MAX_LINES) + ")" if len(items) > MAX_LINES else ""}'.strip(' ')]
    lines += [f'• {text}' for text, _ in items[:MAX_LINES]]
    if len(items) > MAX_LINES:
        lines.append(f'… و{len(items) - MAX_LINES} عملية أخرى')
    lines.append(f'🕐 {time.strftime("%Y-%m-%d %H:%M")}')
    send_telegram_message('\n'.join(lines))


def queue_telegram_line(line, who=None, delay=None):
    """
    يضيف سطراً إلى السجل المجمَّع (بلا طلب شبكة الآن). تُرسل كل الأسطر في رسالة واحدة
    بعد `delay` ثانية (افتراضياً TELEGRAM_BATCH_SECONDS). صامت تماماً عند الفشل.
    """
    if not _is_configured():
        logger.info('Telegram غير مُهيأ - تم تجاهل سطر السجل: %s', line)
        return
    text = line if not who else f'{line} ({who})'
    with _GLOCK:
        _QUEUE.append((text[:200], time.time()))
        if _GTIMER[0] is None:
            timer = threading.Timer(delay if delay is not None else BATCH_DELAY, _flush_queue)
            timer.daemon = True
            _GTIMER[0] = timer
            timer.start()
