"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { QrCode } from "@/components/QrCode";
import * as api from "@/lib/api";
import type { AgentPairingCodeIssued, EventDetail, FtpCredentialIssued } from "@/lib/api";

// NEXT_PUBLIC_SITE_URL, when set, wins over window.location.origin -- the
// QR code has to encode a URL the *scanning device* (a guest's phone) can
// reach, not whatever host happened to load the dashboard in this
// browser tab. Without this, opening the dashboard at localhost:3000
// bakes "localhost" into every QR code, which only ever resolves on the
// machine that generated it -- confirmed by hand: a phone scan of that
// QR tries to reach the phone's own localhost and fails. Same reasoning
// for FTP_HOST below.
const SITE_ORIGIN =
  process.env.NEXT_PUBLIC_SITE_URL || (typeof window !== "undefined" ? window.location.origin : "");
const FTP_HOST =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/^https?:\/\//, "").replace(/:\d+$/, "") ||
  (typeof window !== "undefined" ? window.location.hostname : "");
const FTP_PORT = process.env.NEXT_PUBLIC_FTPS_PORT || "2121";

export function EventCard({ event }: { event: EventDetail }) {
  const { t, locale } = useLocale();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [ftpCredential, setFtpCredential] = useState<FtpCredentialIssued | null>(null);
  const [issuingFtp, setIssuingFtp] = useState(false);
  const [pairingCode, setPairingCode] = useState<AgentPairingCodeIssued | null>(null);
  const [issuingPairingCode, setIssuingPairingCode] = useState(false);
  const [currentSoloNumber, setCurrentSoloNumber] = useState(event.current_solo_number);
  const [advancing, setAdvancing] = useState(false);

  const name = locale === "ar" ? event.name_ar : event.name_en;
  const guestUrl = `${SITE_ORIGIN}/e/${event.qr_token}`;

  // The dashboard page polls listOrgEvents every few seconds -- pick up a
  // number advanced from another device (a second booth screen, or the
  // photographer's own phone) without waiting for a manual "next guest"
  // tap here too.
  useEffect(() => {
    setCurrentSoloNumber(event.current_solo_number);
  }, [event.current_solo_number]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    setUploading(true);
    try {
      await api.uploadPhotos(event.id, files);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleNextGuest() {
    setAdvancing(true);
    try {
      const result = await api.nextGuest(event.id);
      setCurrentSoloNumber(result.current_solo_number);
    } finally {
      setAdvancing(false);
    }
  }

  async function handleIssuePairingCode() {
    setIssuingPairingCode(true);
    try {
      const issued = await api.issueAgentPairingCode(event.id);
      setPairingCode(issued);
    } finally {
      setIssuingPairingCode(false);
    }
  }

  async function handleIssueFtpCredential() {
    setIssuingFtp(true);
    try {
      const credential = await api.issueFtpCredential(event.id);
      setFtpCredential(credential);
    } finally {
      setIssuingFtp(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(guestUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable -- the link is still visible as text below
    }
  }

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5 flex flex-col sm:flex-row gap-5">
      <div className="shrink-0 flex flex-col items-center gap-2">
        <QrCode value={guestUrl} size={120} />
        <button type="button" onClick={copyLink} className="text-xs font-medium text-neutral-500 underline">
          {copied ? "✓" : t("dashboard.events.qr_link")}
        </button>
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">{name}</h3>
            <span
              className={`inline-block mt-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                event.privacy_mode === "strict" ? "bg-purple-100 text-purple-700" : "bg-neutral-100 text-neutral-600"
              }`}
            >
              {event.privacy_mode === "strict"
                ? t("dashboard.events.privacy_strict")
                : t("dashboard.events.privacy_standard")}
            </span>
          </div>
        </div>

        <p className="mt-3 text-sm text-neutral-600">
          {event.photo_count} {t("dashboard.events.photos")} · {event.ready_photo_count}{" "}
          {t("dashboard.events.ready")} · {event.pending_photo_count} {t("dashboard.events.pending")}
        </p>

        {event.match_mode === "sequential" && (
          <div className="mt-4 flex items-center gap-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
            <div>
              <p className="text-xs text-neutral-500">{t("dashboard.events.booth_current_number")}</p>
              <p className="text-3xl font-bold tabular-nums">
                {currentSoloNumber ?? t("dashboard.events.booth_none_yet")}
              </p>
            </div>
            <button
              type="button"
              onClick={handleNextGuest}
              disabled={advancing}
              className="ms-auto rounded-full bg-neutral-900 px-5 py-3 text-sm font-semibold text-white disabled:opacity-60 active:scale-[0.98] transition"
            >
              {advancing ? t("dashboard.events.booth_advancing") : t("dashboard.events.booth_next_guest")}
            </button>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleIssuePairingCode}
            disabled={issuingPairingCode}
            className="rounded-full bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {issuingPairingCode ? t("dashboard.events.pair_agent_generating") : t("dashboard.events.pair_agent")}
          </button>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 disabled:opacity-60"
          >
            {uploading ? t("dashboard.events.uploading") : t("dashboard.events.upload")}
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleUpload} className="hidden" />

          <Link
            href={`/dashboard/events/${event.id}/moderate`}
            className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700"
          >
            {t("dashboard.events.moderate_link")}
          </Link>

          <button
            type="button"
            onClick={handleIssueFtpCredential}
            disabled={issuingFtp}
            className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 disabled:opacity-60"
          >
            {issuingFtp ? t("dashboard.events.ftp_generating") : t("dashboard.events.ftp_credentials")}
          </button>
        </div>

        {pairingCode && (
          <div className="mt-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4 text-sm">
            <p className="text-neutral-600 mb-2">{t("dashboard.events.pair_agent_instructions")}</p>
            <div className="flex items-baseline gap-3" dir="ltr">
              <span className="text-xs text-neutral-500">{t("dashboard.events.pair_agent_code_label")}</span>
              <span className="text-3xl font-bold tracking-widest font-mono">{pairingCode.code}</span>
            </div>
            <p className="mt-1 text-xs text-neutral-500">
              {t("dashboard.events.pair_agent_expires")}{" "}
              {new Date(pairingCode.expires_at).toLocaleTimeString(locale === "ar" ? "ar-SA" : "en-US")}
            </p>
            <button
              type="button"
              onClick={() => setPairingCode(null)}
              className="mt-3 text-xs font-medium text-neutral-600 underline"
            >
              {t("dashboard.events.pair_agent_close")}
            </button>
          </div>
        )}

        {ftpCredential && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">
            <p className="font-medium text-amber-800 mb-2">{t("dashboard.events.ftp_shown_once")}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-neutral-700" dir="ltr">
              <dt className="text-neutral-500">{t("dashboard.events.ftp_host")}</dt>
              <dd className="font-mono">{FTP_HOST}</dd>
              <dt className="text-neutral-500">{t("dashboard.events.ftp_port")}</dt>
              <dd className="font-mono">{FTP_PORT}</dd>
              <dt className="text-neutral-500">{t("dashboard.events.ftp_username")}</dt>
              <dd className="font-mono">{ftpCredential.username}</dd>
              <dt className="text-neutral-500">{t("dashboard.events.ftp_password")}</dt>
              <dd className="font-mono">{ftpCredential.password}</dd>
            </dl>
            <button
              type="button"
              onClick={() => setFtpCredential(null)}
              className="mt-3 text-xs font-medium text-amber-800 underline"
            >
              {t("dashboard.events.ftp_close")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
