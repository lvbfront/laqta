from __future__ import annotations

Locale = str  # "ar" | "en"

DEFAULT_LOCALE: Locale = "ar"

# Same hand-rolled small-dictionary approach as web/lib/i18n.ts -- a
# desktop app with one pairing screen and one status window doesn't
# justify an i18n library either.
STRINGS: dict[Locale, dict[str, str]] = {
    "ar": {
        "app.title": "وكيل لقطة",
        "locale.toggle": "English",
        "pair.title": "ربط الجهاز",
        "pair.instructions": "أدخل رمز الاقتران الظاهر في لوحة تحكم لقطة",
        "pair.code_placeholder": "مثال: A7K2M9",
        "pair.submit": "ربط",
        "pair.pairing": "جارٍ الربط...",
        "pair.error_invalid": "هذا الرمز غير صالح أو منتهي أو تم استخدامه من قبل.",
        "pair.error_network": "تعذّر الاتصال بالخادم. تحقق من اتصال الإنترنت وحاول مرة أخرى.",
        "pair.error_server": "حدث خطأ في الخادم. حاول مرة أخرى بعد قليل.",
        "folder.title": "اختر مجلد الصور",
        "folder.instructions": "اختر المجلد الذي تُحفظ فيه صور الكاميرا. سنراقبه تلقائيًا.",
        "folder.choose": "اختيار مجلد",
        "folder.change": "تغيير المجلد",
        "status.connected": "متصل",
        "status.offline": "غير متصل — الصور تنتظر في الطابور",
        "status.uploaded": "تم الرفع",
        "status.queued": "قيد الانتظار",
        "status.failed": "فشل (سيُعاد المحاولة)",
        "status.folder_label": "المجلد",
        "status.catch_up": "فحص المجلد وإعادة رفع الصور القديمة",
        "status.catch_up_running": "جارٍ الفحص...",
        "status.errors_title": "أخطاء",
        "status.no_errors": "لا توجد أخطاء",
        "status.unpair": "إلغاء الربط",
        "status.unpair_confirm": "سيتم قطع اتصال هذا الجهاز عن الحدث. هل تريد المتابعة؟",
        "error.upload_failed": "فشل رفع الصورة: {filename}",
        "error.network": "لا يوجد اتصال بالإنترنت",
    },
    "en": {
        "app.title": "Laqta Agent",
        "locale.toggle": "العربية",
        "pair.title": "Pair this device",
        "pair.instructions": "Enter the pairing code shown on the Laqta dashboard",
        "pair.code_placeholder": "e.g. A7K2M9",
        "pair.submit": "Pair",
        "pair.pairing": "Pairing...",
        "pair.error_invalid": "That code is invalid, expired, or already used.",
        "pair.error_network": "Couldn't reach the server. Check your internet connection and try again.",
        "pair.error_server": "A server error occurred. Try again shortly.",
        "folder.title": "Choose your photos folder",
        "folder.instructions": "Choose the folder your camera software saves photos to. We'll watch it automatically.",
        "folder.choose": "Choose folder",
        "folder.change": "Change folder",
        "status.connected": "Connected",
        "status.offline": "Offline — photos are queued",
        "status.uploaded": "Uploaded",
        "status.queued": "Queued",
        "status.failed": "Failed (will retry)",
        "status.folder_label": "Folder",
        "status.catch_up": "Scan folder and upload older photos",
        "status.catch_up_running": "Scanning...",
        "status.errors_title": "Errors",
        "status.no_errors": "No errors",
        "status.unpair": "Unpair",
        "status.unpair_confirm": "This device will be disconnected from the event. Continue?",
        "error.upload_failed": "Failed to upload: {filename}",
        "error.network": "No internet connection",
    },
}


def t(locale: Locale, key: str, **kwargs: str) -> str:
    value = STRINGS.get(locale, STRINGS[DEFAULT_LOCALE]).get(key) or STRINGS[DEFAULT_LOCALE].get(key, key)
    if kwargs:
        for k, v in kwargs.items():
            value = value.replace(f"{{{k}}}", v)
    return value
