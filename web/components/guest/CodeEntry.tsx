"use client";

import { useState } from "react";
import { useLocale } from "@/components/LocaleProvider";

export function CodeEntry({
  initialCode,
  submitting,
  onSubmit,
  variant = "code",
}: {
  initialCode?: string;
  submitting: boolean;
  onSubmit: (code: string) => void;
  // match_mode='sequential' guests were handed a plain number by a staff
  // member at the moment they were photographed, not a pre-printed
  // bib/badge -- the copy says so, even though the lookup underneath
  // (POST .../match/code) is identical either way.
  variant?: "code" | "number";
}) {
  const { t } = useLocale();
  const [code, setCode] = useState(initialCode ?? "");
  const titleKey = variant === "number" ? "guest.number_title" : "guest.code_title";
  const instructionsKey = variant === "number" ? "guest.number_instructions" : "guest.code_instructions";
  const placeholderKey = variant === "number" ? "guest.number_placeholder" : "guest.code_placeholder";

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = code.trim();
    if (!trimmed || submitting) return;
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={handleSubmit} className="flex min-h-[100dvh] flex-col justify-center p-6">
      <div className="max-w-md mx-auto w-full flex flex-col gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">{t(titleKey)}</h1>
          <p className="mt-2 text-sm text-neutral-600">{t(instructionsKey)}</p>
        </div>

        <input
          type="text"
          inputMode={variant === "number" ? "numeric" : "text"}
          autoCapitalize="characters"
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder={t(placeholderKey)}
          className="rounded-2xl border border-neutral-300 bg-white px-4 py-4 text-center text-lg tracking-wide"
        />

        <button
          type="submit"
          disabled={!code.trim() || submitting}
          className="w-full rounded-full bg-neutral-900 py-4 text-lg font-semibold text-white shadow-lg
                     disabled:bg-neutral-300 disabled:shadow-none
                     active:scale-[0.98] transition"
        >
          {submitting ? t("guest.code_searching") : t("guest.code_submit")}
        </button>
      </div>
    </form>
  );
}
