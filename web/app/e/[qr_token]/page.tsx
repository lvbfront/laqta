"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { CenteredMessage } from "@/components/CenteredMessage";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";
import { CodeEntry } from "@/components/guest/CodeEntry";
import { ConsentScreen } from "@/components/guest/ConsentScreen";
import { MatchedGallery } from "@/components/guest/MatchedGallery";
import { MatchErrorScreen } from "@/components/guest/MatchErrorScreen";
import { SelfieCapture } from "@/components/guest/SelfieCapture";
import * as api from "@/lib/api";
import type { EventPublic, MatchResult } from "@/lib/api";

type FlowState =
  | { step: "loading" }
  | { step: "error"; message: string }
  | { step: "consent" }
  | { step: "capture" }
  | { step: "code" }
  | { step: "submitting" }
  | { step: "match_error"; code: string; message: string }
  | { step: "gallery"; sessionToken: string; matches: MatchResult[] };

function storageKey(eventId: string) {
  return `laqta_guest_session_${eventId}`;
}

export default function GuestEventPage() {
  const params = useParams<{ qr_token: string }>();
  const searchParams = useSearchParams();
  // A wristband/badge QR can encode a direct URL (/e/[qr_token]?code=XYZ)
  // rather than needing an in-app barcode scanner -- any phone camera app
  // opens it directly. Consent still gates the actual match request (same
  // as the selfie path never auto-fires); this only pre-fills/auto-submits
  // the code once the guest has agreed.
  const codeFromUrl = searchParams.get("code");
  const { t } = useLocale();
  const [event, setEvent] = useState<EventPublic | null>(null);
  const [flow, setFlow] = useState<FlowState>({ step: "loading" });
  // Only meaningful for match_mode='both', where either path is possible --
  // retry-after-error needs to know which screen to go back to.
  const [lastPath, setLastPath] = useState<"face" | "code">("face");

  useEffect(() => {
    let cancelled = false;

    api
      .getEventByToken(params.qr_token)
      .then((ev) => {
        if (cancelled) return;
        setEvent(ev);

        // A reload/back-navigation shouldn't force consent+selfie again --
        // restore the last result for this event if we have one cached.
        try {
          const raw = window.sessionStorage.getItem(storageKey(ev.id));
          if (raw) {
            const saved = JSON.parse(raw) as { sessionToken: string; matches: MatchResult[] };
            setFlow({ step: "gallery", sessionToken: saved.sessionToken, matches: saved.matches });
            return;
          }
        } catch {
          // corrupted/unavailable storage -- fall through to consent
        }
        setFlow({ step: "consent" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof api.ApiError ? err.message : t("error.generic");
        setFlow({ step: "error", message });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.qr_token]);

  async function handleSelfie(blob: Blob) {
    if (!event) return;
    setLastPath("face");
    setFlow({ step: "submitting" });
    try {
      const result = await api.matchSelfie(event.id, blob, true);
      persistAndShowGallery(event.id, result);
    } catch (err) {
      showMatchError(err);
    }
  }

  async function handleCode(code: string) {
    if (!event) return;
    setLastPath("code");
    setFlow({ step: "submitting" });
    try {
      const result = await api.matchByCode(event.id, code);
      persistAndShowGallery(event.id, result);
    } catch (err) {
      showMatchError(err);
    }
  }

  function persistAndShowGallery(eventId: string, result: { guest_session_token: string; matches: MatchResult[] }) {
    try {
      window.sessionStorage.setItem(
        storageKey(eventId),
        JSON.stringify({ sessionToken: result.guest_session_token, matches: result.matches })
      );
    } catch {
      // non-fatal: a reload will just re-run the match
    }
    setFlow({ step: "gallery", sessionToken: result.guest_session_token, matches: result.matches });
  }

  function showMatchError(err: unknown) {
    if (err instanceof api.ApiError) {
      setFlow({ step: "match_error", code: err.code ?? "generic", message: err.message });
    } else {
      setFlow({ step: "match_error", code: "generic", message: t("error.generic") });
    }
  }

  function handleAgree(path: "face" | "code") {
    setLastPath(path);
    if (path === "code" && codeFromUrl) {
      handleCode(codeFromUrl);
      return;
    }
    setFlow({ step: path === "face" ? "capture" : "code" });
  }

  function searchAgain() {
    if (event) {
      try {
        window.sessionStorage.removeItem(storageKey(event.id));
      } catch {
        // ignore
      }
    }
    setFlow({ step: "consent" });
  }

  const showToggle = flow.step !== "loading" && flow.step !== "submitting" && flow.step !== "capture";

  return (
    <div className="min-h-[100dvh]">
      {showToggle && (
        <div className="flex justify-end p-4">
          <LocaleToggle />
        </div>
      )}

      {flow.step === "loading" && <CenteredMessage>{t("common.loading")}</CenteredMessage>}
      {flow.step === "error" && <CenteredMessage tone="error">{flow.message}</CenteredMessage>}
      {flow.step === "submitting" && <CenteredMessage>{t("capture.searching")}</CenteredMessage>}

      {flow.step === "consent" && event && <ConsentScreen event={event} onAgree={handleAgree} />}

      {flow.step === "capture" && <SelfieCapture onCapture={handleSelfie} onBack={() => setFlow({ step: "consent" })} />}

      {flow.step === "code" && (
        <CodeEntry
          initialCode={codeFromUrl ?? undefined}
          submitting={false}
          onSubmit={handleCode}
          variant={event?.match_mode === "sequential" ? "number" : "code"}
        />
      )}

      {flow.step === "match_error" && (
        <MatchErrorScreen
          code={flow.code}
          message={flow.message}
          onRetry={() => setFlow({ step: lastPath === "code" ? "code" : "capture" })}
        />
      )}

      {flow.step === "gallery" && event && (
        <MatchedGallery event={event} sessionToken={flow.sessionToken} matches={flow.matches} onSearchAgain={searchAgain} />
      )}
    </div>
  );
}
