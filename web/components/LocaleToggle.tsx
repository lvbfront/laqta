"use client";

import { useLocale } from "@/components/LocaleProvider";

export function LocaleToggle() {
  const { t, toggleLocale } = useLocale();
  return (
    <button
      type="button"
      onClick={toggleLocale}
      className="rounded-full border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 shadow-sm active:scale-95 transition"
      aria-label="Switch language"
    >
      {t("locale.toggle")}
    </button>
  );
}
