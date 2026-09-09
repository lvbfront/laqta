"use client";

import { useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { PhotoCard } from "@/components/guest/PhotoCard";
import type { EventPublic, MatchResult } from "@/lib/api";

export function MatchedGallery({
  event,
  sessionToken,
  matches,
  onSearchAgain,
}: {
  event: EventPublic;
  sessionToken: string;
  matches: MatchResult[];
  onSearchAgain: () => void;
}) {
  const { t, locale } = useLocale();
  const [photoIds, setPhotoIds] = useState(() => matches.map((m) => m.photo_id));
  const eventName = locale === "ar" ? event.name_ar : event.name_en;

  function handleRemoved(photoId: string) {
    setPhotoIds((ids) => ids.filter((id) => id !== photoId));
  }

  return (
    <div className="min-h-[100dvh] p-4 pb-10">
      <div className="max-w-2xl mx-auto">
        <div className="text-center mb-6">
          <p className="text-sm text-neutral-500">{eventName}</p>
          <h1 className="text-xl font-bold">{t("gallery.title")}</h1>
          <p className="text-sm text-neutral-500 mt-1">
            {photoIds.length === 1
              ? t("gallery.count_one")
              : t("gallery.count_other", { count: photoIds.length })}
          </p>
        </div>

        {photoIds.length === 0 ? (
          <p className="text-center text-neutral-500 py-12">{t("gallery.empty")}</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {photoIds.map((photoId) => (
              <PhotoCard key={photoId} photoId={photoId} sessionToken={sessionToken} onRemoved={handleRemoved} />
            ))}
          </div>
        )}

        <button
          type="button"
          onClick={onSearchAgain}
          className="mt-8 w-full rounded-full border border-neutral-300 py-3 text-sm font-medium text-neutral-700 active:scale-[0.98] transition"
        >
          {t("gallery.search_again")}
        </button>
      </div>
    </div>
  );
}
