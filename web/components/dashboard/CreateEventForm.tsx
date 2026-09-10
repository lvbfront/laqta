"use client";

import { useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import * as api from "@/lib/api";
import type { EventDetail } from "@/lib/api";

export function CreateEventForm({ orgId, onCreated }: { orgId: string; onCreated: (event: EventDetail) => void }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [nameAr, setNameAr] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [privacyMode, setPrivacyMode] = useState<"standard" | "strict">("standard");
  const [matchMode, setMatchMode] = useState<"face" | "code" | "both" | "sequential">("face");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = nameAr.trim() && nameEn.trim() && endsAt && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const event = await api.createEvent(orgId, {
        name_ar: nameAr.trim(),
        name_en: nameEn.trim(),
        ends_at: new Date(endsAt).toISOString(),
        privacy_mode: privacyMode,
        match_mode: matchMode,
      });
      onCreated(event);
      setNameAr("");
      setNameEn("");
      setEndsAt("");
      setPrivacyMode("standard");
      setMatchMode("face");
      setOpen(false);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : t("error.generic"));
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-2xl border-2 border-dashed border-neutral-300 py-4 text-sm font-medium text-neutral-600 hover:border-neutral-400 transition"
      >
        + {t("dashboard.events.create")}
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-2xl border border-neutral-200 bg-white p-5 flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("dashboard.events.name_ar")}</span>
          <input
            dir="rtl"
            value={nameAr}
            onChange={(e) => setNameAr(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2"
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("dashboard.events.name_en")}</span>
          <input
            dir="ltr"
            value={nameEn}
            onChange={(e) => setNameEn(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2"
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("dashboard.events.ends_at")}</span>
          <input
            type="datetime-local"
            value={endsAt}
            onChange={(e) => setEndsAt(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2"
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("dashboard.events.privacy_mode")}</span>
          <select
            value={privacyMode}
            onChange={(e) => setPrivacyMode(e.target.value as "standard" | "strict")}
            className="rounded-lg border border-neutral-300 px-3 py-2"
          >
            <option value="standard">{t("dashboard.events.privacy_standard")}</option>
            <option value="strict">{t("dashboard.events.privacy_strict")}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("dashboard.events.match_mode")}</span>
          <select
            value={matchMode}
            onChange={(e) => setMatchMode(e.target.value as "face" | "code" | "both" | "sequential")}
            className="rounded-lg border border-neutral-300 px-3 py-2"
          >
            <option value="face">{t("dashboard.events.match_mode_face")}</option>
            <option value="code">{t("dashboard.events.match_mode_code")}</option>
            <option value="both">{t("dashboard.events.match_mode_both")}</option>
            <option value="sequential">{t("dashboard.events.match_mode_sequential")}</option>
          </select>
        </label>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-full border border-neutral-300 px-5 py-2 text-sm font-medium"
        >
          {t("common.back")}
        </button>
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-full bg-neutral-900 px-5 py-2 text-sm font-semibold text-white disabled:bg-neutral-300"
        >
          {submitting ? t("dashboard.events.creating") : t("dashboard.events.create_submit")}
        </button>
      </div>
    </form>
  );
}
