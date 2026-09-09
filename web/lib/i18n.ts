export type Locale = "ar" | "en";

export const DEFAULT_LOCALE: Locale = "ar";
export const LOCALE_STORAGE_KEY = "laqta_locale";

// Small, hand-rolled dictionary rather than a full i18n library -- Phase 1
// has three routes and a bounded set of strings; a library's routing/
// bundle-splitting machinery would be pure overhead here. Keys are plain
// English phrases (not a codes-and-lookups scheme) so a missing Arabic
// string still reads fine as a fallback.
export const dictionaries: Record<Locale, Record<string, string>> = {
  ar: {
    "app.name": "لقطة",
    "locale.toggle": "English",

    // Guest: consent
    "consent.title": "قبل أن نبدأ",
    "consent.checkbox": "أوافق على استخدام صورة وجهي مؤقتًا للبحث عن صوري في هذا الحدث",
    "consent.checkbox_code": "أوافق على استخدام رمز الشارة الخاص بي للبحث عن صوري في هذا الحدث",
    "consent.continue": "متابعة",
    "consent.privacy_strict_note": "هذا حدث خاص: لا يمكن لأحد تصفح الصور، وتُحذف بياناتك خلال 7 أيام من انتهاء الحدث.",
    "consent.privacy_standard_note": "تُحذف بياناتك تلقائيًا خلال 30 يومًا من انتهاء الحدث.",

    // Guest: capture
    "capture.title": "التقط صورة سيلفي",
    "capture.instructions": "انظر مباشرة إلى الكاميرا في إضاءة جيدة",
    "capture.button": "التقاط",
    "capture.retake": "إعادة المحاولة",
    "capture.use_photo": "استخدام هذه الصورة",
    "capture.upload_fallback": "أو اختر صورة من جهازك",
    "capture.camera_unavailable": "الكاميرا غير متاحة على هذا الجهاز. اختر صورة بدلاً من ذلك.",
    "capture.searching": "جارِ البحث عن صورك...",

    // Match errors
    "error.no_face_detected": "لم نتمكن من العثور على وجه في الصورة. تأكد من ظهور وجهك بوضوح وحاول مرة أخرى.",
    "error.multiple_faces_detected": "تم رصد أكثر من وجه واحد. التقط صورة لنفسك وحدك.",
    "error.low_detection_confidence": "لم نتمكن من رؤية وجهك بوضوح. جرّب إضاءة أفضل، وأزل النظارة الشمسية أو الكمامة إن وُجدت.",
    "error.face_too_small": "وجهك صغير جدًا في الصورة. اقترب من الكاميرا وحاول مرة أخرى.",
    "error.selfie_too_blurry": "الصورة غير واضحة. ثبّت الكاميرا جيدًا وحاول مرة أخرى.",
    "error.empty_selfie": "لم يتم استلام أي صورة. حاول مرة أخرى.",
    "error.selfie_too_large": "حجم الصورة كبير جدًا. جرّب صورة أخرى.",
    "error.consent_required": "الموافقة مطلوبة للمتابعة.",
    "error.event_not_found": "لم يتم العثور على هذا الحدث. تحقق من رمز QR.",
    "error.generic": "حدث خطأ ما. حاول مرة أخرى.",
    "error.try_again": "حاول مرة أخرى",

    // Guest: gallery
    "gallery.title": "صورك",
    "gallery.count_one": "تم العثور على صورة واحدة",
    "gallery.count_other": "تم العثور على {count} صورة",
    "gallery.empty": "لم نعثر على صور لك في هذا الحدث بعد. جرّب مرة أخرى لاحقًا.",
    "gallery.search_again": "بحث جديد",
    "gallery.download": "تنزيل",
    "gallery.downloading": "جارِ التنزيل...",
    "gallery.not_me": "هذا ليس أنا",
    "gallery.not_me_done": "شكرًا، تم إرسال ملاحظتك",
    "gallery.remove": "إزالة صورتي",
    "gallery.remove_confirm": "سيتم إخفاء هذه الصورة عن الجميع نهائيًا. متابعة؟",
    "gallery.remove_done": "تمت إزالة الصورة",

    // Dashboard
    "dashboard.events.title": "الفعاليات",
    "dashboard.events.create": "إنشاء فعالية",
    "dashboard.events.name_ar": "اسم الفعالية (عربي)",
    "dashboard.events.name_en": "اسم الفعالية (إنجليزي)",
    "dashboard.events.ends_at": "تاريخ ووقت الانتهاء",
    "dashboard.events.privacy_mode": "وضع الخصوصية",
    "dashboard.events.privacy_standard": "عادي",
    "dashboard.events.privacy_strict": "صارم (فعاليات نسائية)",
    "dashboard.events.create_submit": "إنشاء",
    "dashboard.events.creating": "جارِ الإنشاء...",
    "dashboard.events.empty": "لا توجد فعاليات بعد.",
    "dashboard.events.photos": "صورة",
    "dashboard.events.ready": "جاهزة",
    "dashboard.events.pending": "قيد المعالجة",
    "dashboard.events.qr_link": "رابط الضيوف",
    "dashboard.events.moderate_link": "المراجعة",
    "dashboard.events.upload": "رفع صور",
    "dashboard.events.uploading": "جارِ الرفع...",

    "dashboard.moderate.title": "مراجعة الصور",
    "dashboard.moderate.empty": "لا توجد صور بانتظار المراجعة.",
    "dashboard.moderate.approve": "اعتماد",
    "dashboard.moderate.reject": "رفض",
    "dashboard.moderate.back": "رجوع إلى الفعاليات",

    "dashboard.events.match_mode": "طريقة المطابقة",
    "dashboard.events.match_mode_face": "سيلفي (تعرف على الوجه)",
    "dashboard.events.match_mode_code": "رمز (سوار/شارة، بدون بيانات حيوية)",
    "dashboard.events.match_mode_both": "كلاهما",
    "dashboard.events.logout": "تسجيل الخروج",

    "dashboard.moderate.codes_label": "رموز الشارة/السوار",
    "dashboard.moderate.codes_placeholder": "أدخل رمزًا",
    "dashboard.moderate.codes_add": "إضافة",

    "auth.login_title": "تسجيل الدخول",
    "auth.register_title": "إنشاء حساب منظِّم",
    "auth.org_name": "اسم المنظمة",
    "auth.email": "البريد الإلكتروني",
    "auth.password": "كلمة المرور",
    "auth.login_submit": "دخول",
    "auth.register_submit": "إنشاء حساب",
    "auth.switch_to_register": "ليس لديك حساب؟ أنشئ واحدًا",
    "auth.switch_to_login": "لديك حساب بالفعل؟ سجّل الدخول",
    "auth.submitting": "جارٍ الإرسال...",

    "guest.code_title": "أدخل رمز الشارة",
    "guest.code_instructions": "أدخل الرمز الموجود على شارتك أو سوارك للعثور على صورك",
    "guest.code_placeholder": "مثال: BIB1234",
    "guest.code_submit": "بحث",
    "guest.code_searching": "جارِ البحث...",

    "common.loading": "جارِ التحميل...",
    "common.back": "رجوع",
  },
  en: {
    "app.name": "Laqta",
    "locale.toggle": "العربية",

    "consent.title": "Before we start",
    "consent.checkbox": "I consent to my face being used temporarily to find my photos from this event",
    "consent.checkbox_code": "I consent to my badge code being used to find my photos from this event",
    "consent.continue": "Continue",
    "consent.privacy_strict_note": "This is a private event: no one can browse the photos, and your data is deleted within 7 days of the event ending.",
    "consent.privacy_standard_note": "Your data is automatically deleted within 30 days of the event ending.",

    "capture.title": "Take a selfie",
    "capture.instructions": "Look directly at the camera in good light",
    "capture.button": "Capture",
    "capture.retake": "Retake",
    "capture.use_photo": "Use this photo",
    "capture.upload_fallback": "Or choose a photo from your device",
    "capture.camera_unavailable": "Camera isn't available on this device. Choose a photo instead.",
    "capture.searching": "Searching for your photos...",

    "error.no_face_detected": "We couldn't find a face in your photo. Make sure your face is clearly visible and try again.",
    "error.multiple_faces_detected": "We detected more than one face. Please take a selfie of yourself alone.",
    "error.low_detection_confidence": "We couldn't get a clear reading of your face. Try better lighting, and remove sunglasses or a mask if you're wearing one.",
    "error.face_too_small": "Your face is too small in the frame. Move closer to the camera and try again.",
    "error.selfie_too_blurry": "Your photo looks blurry. Hold the camera steady and try again.",
    "error.empty_selfie": "No image was received. Please try again.",
    "error.selfie_too_large": "That image is too large. Try a different photo.",
    "error.consent_required": "Consent is required to continue.",
    "error.event_not_found": "This event couldn't be found. Check the QR code.",
    "error.generic": "Something went wrong. Please try again.",
    "error.try_again": "Try again",

    "gallery.title": "Your photos",
    "gallery.count_one": "Found 1 photo",
    "gallery.count_other": "Found {count} photos",
    "gallery.empty": "We haven't found any photos of you at this event yet. Try again later.",
    "gallery.search_again": "Search again",
    "gallery.download": "Download",
    "gallery.downloading": "Downloading...",
    "gallery.not_me": "This isn't me",
    "gallery.not_me_done": "Thanks, your feedback was sent",
    "gallery.remove": "Remove this photo of me",
    "gallery.remove_confirm": "This photo will be hidden from everyone, permanently. Continue?",
    "gallery.remove_done": "Photo removed",

    "dashboard.events.title": "Events",
    "dashboard.events.create": "Create event",
    "dashboard.events.name_ar": "Event name (Arabic)",
    "dashboard.events.name_en": "Event name (English)",
    "dashboard.events.ends_at": "Ends at",
    "dashboard.events.privacy_mode": "Privacy mode",
    "dashboard.events.privacy_standard": "Standard",
    "dashboard.events.privacy_strict": "Strict (women's events)",
    "dashboard.events.create_submit": "Create",
    "dashboard.events.creating": "Creating...",
    "dashboard.events.empty": "No events yet.",
    "dashboard.events.photos": "photos",
    "dashboard.events.ready": "ready",
    "dashboard.events.pending": "processing",
    "dashboard.events.qr_link": "Guest link",
    "dashboard.events.moderate_link": "Moderate",
    "dashboard.events.upload": "Upload photos",
    "dashboard.events.uploading": "Uploading...",

    "dashboard.moderate.title": "Moderate photos",
    "dashboard.moderate.empty": "No photos waiting for review.",
    "dashboard.moderate.approve": "Approve",
    "dashboard.moderate.reject": "Reject",
    "dashboard.moderate.back": "Back to events",

    "dashboard.events.match_mode": "Match mode",
    "dashboard.events.match_mode_face": "Selfie (face recognition)",
    "dashboard.events.match_mode_code": "Code (wristband/badge, no biometric data)",
    "dashboard.events.match_mode_both": "Both",
    "dashboard.events.logout": "Log out",

    "dashboard.moderate.codes_label": "Bib/badge codes",
    "dashboard.moderate.codes_placeholder": "Enter a code",
    "dashboard.moderate.codes_add": "Add",

    "auth.login_title": "Sign in",
    "auth.register_title": "Create an organizer account",
    "auth.org_name": "Organization name",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.login_submit": "Sign in",
    "auth.register_submit": "Create account",
    "auth.switch_to_register": "Don't have an account? Create one",
    "auth.switch_to_login": "Already have an account? Sign in",
    "auth.submitting": "Submitting...",

    "guest.code_title": "Enter your badge code",
    "guest.code_instructions": "Enter the code on your badge or wristband to find your photos",
    "guest.code_placeholder": "e.g. BIB1234",
    "guest.code_submit": "Search",
    "guest.code_searching": "Searching...",

    "common.loading": "Loading...",
    "common.back": "Back",
  },
};

export function translate(locale: Locale, key: string, vars?: Record<string, string | number>): string {
  let value = dictionaries[locale][key] ?? dictionaries[DEFAULT_LOCALE][key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      value = value.replace(`{${k}}`, String(v));
    }
  }
  return value;
}
