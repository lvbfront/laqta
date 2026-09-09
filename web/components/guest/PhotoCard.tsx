"use client";

import { useEffect, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import * as api from "@/lib/api";

export function PhotoCard({
  photoId,
  sessionToken,
  onRemoved,
}: {
  photoId: string;
  sessionToken: string;
  onRemoved: (photoId: string) => void;
}) {
  const { t } = useLocale();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [notMeSent, setNotMeSent] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getSignedPhotoUrl(photoId, sessionToken, "preview")
      .then((res) => {
        if (!cancelled) setPreviewUrl(res.url);
      })
      .catch(() => {
        /* a single photo's preview failing shouldn't break the rest of the gallery */
      });
    return () => {
      cancelled = true;
    };
  }, [photoId, sessionToken]);

  async function handleDownload() {
    setDownloading(true);
    try {
      const { url } = await api.getSignedPhotoUrl(photoId, sessionToken, "original");
      // Content-Disposition: attachment is signed into this URL server-side
      // (see app/api/routes/delivery.py) -- navigating to it downloads the
      // file rather than opening it inline.
      window.location.href = url;
    } finally {
      setDownloading(false);
    }
  }

  async function handleNotMe() {
    setNotMeSent(true);
    try {
      await api.reportNotMe(photoId, sessionToken);
    } catch {
      setNotMeSent(false);
    }
  }

  async function handleRemove() {
    setConfirmingRemove(false);
    try {
      await api.requestPhotoRemoval(photoId, sessionToken);
      onRemoved(photoId);
    } catch {
      // stays in the gallery if the request failed -- the guest can retry
    }
  }

  return (
    <div className="rounded-2xl overflow-hidden bg-white border border-neutral-200 shadow-sm">
      <div className="aspect-square bg-neutral-100">
        {previewUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={previewUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
        )}
      </div>

      <div className="p-3 flex flex-col gap-2">
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="w-full rounded-full bg-neutral-900 py-3 text-sm font-semibold text-white disabled:opacity-60 active:scale-[0.98] transition"
        >
          {downloading ? t("gallery.downloading") : t("gallery.download")}
        </button>

        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={handleNotMe}
            disabled={notMeSent}
            className="flex-1 rounded-full border border-neutral-300 py-2 font-medium text-neutral-700 disabled:text-neutral-400 active:scale-[0.98] transition"
          >
            {notMeSent ? t("gallery.not_me_done") : t("gallery.not_me")}
          </button>
          <button
            type="button"
            onClick={() => setConfirmingRemove(true)}
            className="flex-1 rounded-full border border-red-200 py-2 font-medium text-red-600 active:scale-[0.98] transition"
          >
            {t("gallery.remove")}
          </button>
        </div>
      </div>

      {confirmingRemove && (
        <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/50 p-4" onClick={() => setConfirmingRemove(false)}>
          <div
            className="w-full max-w-sm rounded-2xl bg-white p-5 flex flex-col gap-4"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-sm text-neutral-700">{t("gallery.remove_confirm")}</p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setConfirmingRemove(false)}
                className="flex-1 rounded-full border border-neutral-300 py-3 font-medium"
              >
                {t("common.back")}
              </button>
              <button
                type="button"
                onClick={handleRemove}
                className="flex-1 rounded-full bg-red-600 py-3 font-semibold text-white"
              >
                {t("gallery.remove")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
