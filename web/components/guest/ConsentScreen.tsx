"use client";

import { useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import type { EventPublic } from "@/lib/api";

export function ConsentScreen({
  event,
  onAgree,
}: {
  event: EventPublic;
  onAgree: (path: "face" | "code") => void;
}) {
  const { t, locale } = useLocale();
  // Never pre-ticked, on purpose -- this is the one checkbox in the app
  // that must never default to checked, per CLAUDE.md.
  const [checked, setChecked] = useState(false);

  const consentText = locale === "ar" ? event.consent_text_ar : event.consent_text_en;
  const eventName = locale === "ar" ? event.name_ar : event.name_en;
  const showFaceButton = event.match_mode === "face" || event.match_mode === "both";
  const showCodeButton = event.match_mode === "code" || event.match_mode === "both" || event.match_mode === "sequential";
  // "code" and "sequential" are both biometric-free, just different ways
  // a photo gets tagged with a number/code -- same non-face consent copy.
  const isBiometricFree = event.match_mode === "code" || event.match_mode === "sequential";

  return (
    <div className="flex min-h-[100dvh] flex-col justify-between p-6">
      <div className="flex-1 flex flex-col justify-center gap-6 max-w-md mx-auto w-full">
        <div className="text-center">
          <p className="text-sm text-neutral-500">{eventName}</p>
          <h1 className="text-2xl font-bold mt-1">{t("consent.title")}</h1>
        </div>

        {/* Full bilingual-per-current-locale text straight from the event
            record -- organizer-authored, not app chrome. */}
        <p className="rounded-2xl bg-white border border-neutral-200 p-4 text-sm leading-relaxed text-neutral-700 whitespace-pre-wrap">
          {consentText}
        </p>

        <p className="text-xs text-neutral-500 text-center">
          {event.privacy_mode === "strict" ? t("consent.privacy_strict_note") : t("consent.privacy_standard_note")}
        </p>

        <label className="flex items-start gap-3 rounded-2xl bg-white border border-neutral-200 p-4 cursor-pointer select-none active:bg-neutral-50">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            className="mt-0.5 h-6 w-6 shrink-0 rounded border-neutral-300"
          />
          <span className="text-sm font-medium">
            {isBiometricFree ? t("consent.checkbox_code") : t("consent.checkbox")}
          </span>
        </label>
      </div>

      <div className="mt-6 flex flex-col gap-3 max-w-md mx-auto w-full">
        {showFaceButton && (
          <button
            type="button"
            disabled={!checked}
            onClick={() => onAgree("face")}
            className="w-full rounded-full bg-neutral-900 py-4 text-lg font-semibold text-white shadow-lg
                       disabled:bg-neutral-300 disabled:shadow-none
                       active:scale-[0.98] transition"
          >
            {showCodeButton ? t("capture.title") : t("consent.continue")}
          </button>
        )}
        {showCodeButton && (
          <button
            type="button"
            disabled={!checked}
            onClick={() => onAgree("code")}
            className={
              showFaceButton
                ? "w-full rounded-full border-2 border-neutral-900 py-4 text-lg font-semibold text-neutral-900 disabled:border-neutral-300 disabled:text-neutral-300 active:scale-[0.98] transition"
                : "w-full rounded-full bg-neutral-900 py-4 text-lg font-semibold text-white shadow-lg disabled:bg-neutral-300 disabled:shadow-none active:scale-[0.98] transition"
            }
          >
            {showFaceButton ? t("guest.code_title") : t("consent.continue")}
          </button>
        )}
      </div>
    </div>
  );
}
