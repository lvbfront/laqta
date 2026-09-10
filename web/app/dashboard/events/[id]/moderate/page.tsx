"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CenteredMessage } from "@/components/CenteredMessage";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";
import * as api from "@/lib/api";
import type { EventDetail, PhotoListItem } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";

export default function ModeratePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { t, locale } = useLocale();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [photos, setPhotos] = useState<PhotoListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [codeDrafts, setCodeDrafts] = useState<Record<string, string>>({});

  async function refresh() {
    const [ev, readyPhotos] = await Promise.all([api.getEvent(params.id), api.listPhotos(params.id, "ready")]);
    setEvent(ev);
    // The list endpoint only filters by processing status -- "awaiting
    // review" specifically means ready *and* not yet published, filtered
    // here rather than adding a second query param for it. Note: a
    // rejected photo also has published=false, so (Phase 1 limitation,
    // no separate "rejected" state in the schema) it will reappear here
    // rather than staying dismissed -- see app/api/routes/photos.py.
    //
    // Exception: a code-mode event's photos still need someone to type in
    // a bib/badge code, and with privacy_mode='standard' (the common case)
    // auto_publish means a photo is *already* published the moment it's
    // ready -- it would never reach this page at all under the
    // unpublished-only filter, and staff would have no way to tag it.
    // Code-mode events therefore show every ready photo here, published or
    // not; approve/reject remain available too (still meaningful for a
    // strict code-mode event, or to unpublish a mistagged photo).
    const showAllReady = ev.match_mode === "code" || ev.match_mode === "both" || ev.match_mode === "sequential";
    setPhotos(showAllReady ? readyPhotos : readyPhotos.filter((p) => !p.published));
  }

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh().catch((err) => {
      if (err instanceof api.ApiError && err.status === 401) {
        clearToken();
        router.replace("/login");
        return;
      }
      setError(err instanceof api.ApiError ? err.message : t("error.generic"));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  async function handleModerate(photoId: string, action: "approve" | "reject") {
    setPendingIds((prev) => new Set(prev).add(photoId));
    try {
      await api.moderatePhoto(params.id, photoId, action);
      setPhotos((prev) => (prev ? prev.filter((p) => p.id !== photoId) : prev));
    } catch {
      // left in the queue so the organizer can retry
    } finally {
      setPendingIds((prev) => {
        const next = new Set(prev);
        next.delete(photoId);
        return next;
      });
    }
  }

  async function handleAddCode(photoId: string) {
    const code = (codeDrafts[photoId] ?? "").trim();
    if (!code) return;
    try {
      const result = await api.addPhotoCode(params.id, photoId, code);
      setPhotos((prev) =>
        prev ? prev.map((p) => (p.id === photoId ? { ...p, codes: result.codes } : p)) : prev
      );
      setCodeDrafts((prev) => ({ ...prev, [photoId]: "" }));
    } catch {
      // draft stays filled in so the organizer can retry
    }
  }

  async function handleRemoveCode(photoId: string, code: string) {
    try {
      const result = await api.removePhotoCode(params.id, photoId, code);
      setPhotos((prev) =>
        prev ? prev.map((p) => (p.id === photoId ? { ...p, codes: result.codes } : p)) : prev
      );
    } catch {
      // no-op -- the tag stays visible so the organizer can retry
    }
  }

  if (error) return <CenteredMessage tone="error">{error}</CenteredMessage>;
  if (!event || photos === null) return <CenteredMessage>{t("common.loading")}</CenteredMessage>;

  const name = locale === "ar" ? event.name_ar : event.name_en;
  const showCodeTagging = event.match_mode === "code" || event.match_mode === "both" || event.match_mode === "sequential";

  return (
    <div className="min-h-[100dvh] p-4 sm:p-8">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-2">
          <Link href="/dashboard/events" className="text-sm text-neutral-500 underline">
            {t("dashboard.moderate.back")}
          </Link>
          <LocaleToggle />
        </div>
        <h1 className="text-2xl font-bold mb-1">{t("dashboard.moderate.title")}</h1>
        <p className="text-sm text-neutral-500 mb-6">{name}</p>

        {photos.length === 0 ? (
          <p className="text-center text-neutral-500 py-12">{t("dashboard.moderate.empty")}</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {photos.map((photo) => {
              const busy = pendingIds.has(photo.id);
              return (
                <div key={photo.id} className="rounded-2xl overflow-hidden bg-white border border-neutral-200">
                  <div className="aspect-square bg-neutral-100">
                    {photo.thumbnail_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={photo.thumbnail_url} alt="" className="h-full w-full object-cover" />
                    )}
                  </div>

                  {showCodeTagging && (
                    <div className="px-3 pt-3">
                      <p className="text-[11px] font-medium text-neutral-500 mb-1">
                        {t("dashboard.moderate.codes_label")}
                      </p>
                      {photo.codes.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-2">
                          {photo.codes.map((code) => (
                            <button
                              key={code}
                              type="button"
                              onClick={() => handleRemoveCode(photo.id, code)}
                              className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700"
                              title={code}
                            >
                              {code} ×
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="flex gap-1">
                        <input
                          value={codeDrafts[photo.id] ?? ""}
                          onChange={(e) => setCodeDrafts((prev) => ({ ...prev, [photo.id]: e.target.value }))}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              handleAddCode(photo.id);
                            }
                          }}
                          placeholder={t("dashboard.moderate.codes_placeholder")}
                          className="min-w-0 flex-1 rounded-lg border border-neutral-300 px-2 py-1 text-xs"
                        />
                        <button
                          type="button"
                          onClick={() => handleAddCode(photo.id)}
                          className="rounded-lg bg-neutral-900 px-2 py-1 text-xs font-medium text-white shrink-0"
                        >
                          {t("dashboard.moderate.codes_add")}
                        </button>
                      </div>
                    </div>
                  )}

                  <div className="p-3 flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleModerate(photo.id, "reject")}
                      className="flex-1 rounded-full border border-red-200 py-2 text-xs font-semibold text-red-600 disabled:opacity-50 active:scale-[0.98] transition"
                    >
                      {t("dashboard.moderate.reject")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleModerate(photo.id, "approve")}
                      className="flex-1 rounded-full bg-neutral-900 py-2 text-xs font-semibold text-white disabled:opacity-50 active:scale-[0.98] transition"
                    >
                      {t("dashboard.moderate.approve")}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
