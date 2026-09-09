"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CenteredMessage } from "@/components/CenteredMessage";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";
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
  | { step: "submitting" }
  | { step: "match_error"; code: string; message: string }
  | { step: "gallery"; sessionToken: string; matches: MatchResult[] };

function storageKey(eventId: string) {
  return `laqta_guest_session_${eventId}`;
}

export default function GuestEventPage() {
  const params = useParams<{ qr_token: string }>();
  const { t } = useLocale();
  const [event, setEvent] = useState<EventPublic | null>(null);
  const [flow, setFlow] = useState<FlowState>({ step: "loading" });

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
    setFlow({ step: "submitting" });
    try {
      const result = await api.matchSelfie(event.id, blob, true);
      try {
        window.sessionStorage.setItem(
          storageKey(event.id),
          JSON.stringify({ sessionToken: result.guest_session_token, matches: result.matches })
        );
      } catch {
        // non-fatal: a reload will just re-run the match
      }
      setFlow({ step: "gallery", sessionToken: result.guest_session_token, matches: result.matches });
    } catch (err) {
      if (err instanceof api.ApiError) {
        setFlow({ step: "match_error", code: err.code ?? "generic", message: err.message });
      } else {
        setFlow({ step: "match_error", code: "generic", message: t("error.generic") });
      }
    }
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

      {flow.step === "consent" && event && <ConsentScreen event={event} onAgree={() => setFlow({ step: "capture" })} />}

      {flow.step === "capture" && <SelfieCapture onCapture={handleSelfie} onBack={() => setFlow({ step: "consent" })} />}

      {flow.step === "match_error" && (
        <MatchErrorScreen code={flow.code} message={flow.message} onRetry={() => setFlow({ step: "capture" })} />
      )}

      {flow.step === "gallery" && event && (
        <MatchedGallery event={event} sessionToken={flow.sessionToken} matches={flow.matches} onSearchAgain={searchAgain} />
      )}
    </div>
  );
}
