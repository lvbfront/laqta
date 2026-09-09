"use client";

import { useLocale } from "@/components/LocaleProvider";

const KNOWN_CODES = new Set([
  "no_face_detected",
  "multiple_faces_detected",
  "low_detection_confidence",
  "face_too_small",
  "selfie_too_blurry",
  "empty_selfie",
  "selfie_too_large",
  "consent_required",
]);

// Surfaces the match API's error `code` as specific, actionable guidance --
// not a generic "something went wrong, try again". Falls back to the
// server's own message text for a code this build doesn't recognize yet,
// so a new backend error code degrades gracefully instead of showing
// nothing.
export function MatchErrorScreen({
  code,
  message,
  onRetry,
}: {
  code: string;
  message: string;
  onRetry: () => void;
}) {
  const { t } = useLocale();
  const text = KNOWN_CODES.has(code) ? t(`error.${code}`) : message || t("error.generic");

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 p-6 text-center">
      <div className="max-w-sm space-y-3">
        <div className="mx-auto h-14 w-14 rounded-full bg-amber-100 flex items-center justify-center text-2xl">
          ⚠️
        </div>
        <p className="text-lg font-medium">{text}</p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="w-full max-w-sm rounded-full bg-neutral-900 py-4 text-lg font-semibold text-white active:scale-[0.98] transition"
      >
        {t("error.try_again")}
      </button>
    </div>
  );
}
