"use client";

import { useEffect, useRef, useState } from "react";
import { CenteredMessage } from "@/components/CenteredMessage";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";
import { CreateEventForm } from "@/components/dashboard/CreateEventForm";
import { EventCard } from "@/components/dashboard/EventCard";
import * as api from "@/lib/api";
import type { EventDetail } from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

export default function DashboardEventsPage() {
  const { t } = useLocale();
  const [orgId, setOrgId] = useState<string | null>(null);
  const [events, setEvents] = useState<EventDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function refresh(currentOrgId: string) {
    try {
      const list = await api.listOrgEvents(currentOrgId);
      setEvents(list);
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : t("error.generic"));
    }
  }

  useEffect(() => {
    let cancelled = false;
    api
      .getDefaultOrganization()
      .then((org) => {
        if (cancelled) return;
        setOrgId(org.id);
        return refresh(org.id);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof api.ApiError ? err.message : t("error.generic"));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // "Live" upload count: no websocket/SSE in Phase 1 -- polling the event
  // list is the simple, adequate mechanism while this page is open.
  useEffect(() => {
    if (!orgId) return;
    pollRef.current = setInterval(() => refresh(orgId), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  function handleCreated(event: EventDetail) {
    setEvents((prev) => (prev ? [event, ...prev] : [event]));
  }

  if (error) return <CenteredMessage tone="error">{error}</CenteredMessage>;
  if (!orgId || events === null) return <CenteredMessage>{t("common.loading")}</CenteredMessage>;

  return (
    <div className="min-h-[100dvh] p-4 sm:p-8">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">{t("dashboard.events.title")}</h1>
          <LocaleToggle />
        </div>

        <div className="flex flex-col gap-4">
          <CreateEventForm orgId={orgId} onCreated={handleCreated} />

          {events.length === 0 ? (
            <p className="text-center text-neutral-500 py-12">{t("dashboard.events.empty")}</p>
          ) : (
            events.map((event) => <EventCard key={event.id} event={event} />)
          )}
        </div>
      </div>
    </div>
  );
}
