"use client";

import { useMemo, useState } from "react";
import type { HelpContent } from "@/app/help/camera/content";
import camerasData from "@/app/help/camera/cameras.json";

interface Camera {
  brand: string;
  model: string;
  hasBuiltInFtp: boolean;
  note?: string;
}

const CAMERAS = (camerasData.cameras as Camera[]).slice().sort((a, b) => a.brand.localeCompare(b.brand));

export type Verdict = "ftp" | "agent" | "not_listed" | null;

export function CameraSelector({
  content,
  onVerdict,
}: {
  content: HelpContent;
  onVerdict: (verdict: Verdict) => void;
}) {
  const s = content.selector;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<Verdict>(null);
  const [matchedNote, setMatchedNote] = useState<string | undefined>(undefined);

  const results = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length === 0) return [];
    // Every typed word must appear somewhere in "brand model", in any
    // order -- a plain contiguous-substring match would miss "Canon R5"
    // against "Canon EOS R5" (real bug, caught live: "EOS" sitting
    // between the two words the user actually typed broke a naive
    // .includes() search entirely).
    return CAMERAS.filter((c) => {
      const haystack = `${c.brand} ${c.model}`.toLowerCase();
      return words.every((w) => haystack.includes(w));
    }).slice(0, 8);
  }, [query]);

  function pick(camera: Camera) {
    setSelectedLabel(`${camera.brand} ${camera.model}`);
    setQuery(`${camera.brand} ${camera.model}`);
    setOpen(false);
    setMatchedNote(camera.note);
    const v: Verdict = camera.hasBuiltInFtp ? "ftp" : "agent";
    setVerdict(v);
    onVerdict(v);
  }

  function pickNotListed() {
    setSelectedLabel(s.notListedLabel);
    setQuery("");
    setOpen(false);
    setMatchedNote(undefined);
    setVerdict("not_listed");
    onVerdict("not_listed");
  }

  function reset() {
    setSelectedLabel(null);
    setQuery("");
    setVerdict(null);
    setMatchedNote(undefined);
    onVerdict(null);
  }

  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5">
      <h2 className="text-lg font-bold mb-3">{s.heading}</h2>

      {!selectedLabel ? (
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            placeholder={s.placeholder}
            className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
          />
          {open && query.trim() && (
            <div className="absolute z-10 mt-1 w-full rounded-lg border border-neutral-200 bg-white shadow-lg max-h-64 overflow-y-auto">
              {results.length === 0 ? (
                <p className="px-3 py-2 text-sm text-neutral-500">{s.noResults}</p>
              ) : (
                results.map((c) => (
                  <button
                    key={`${c.brand}-${c.model}`}
                    type="button"
                    onClick={() => pick(c)}
                    className="w-full text-start px-3 py-2 text-sm hover:bg-neutral-50 border-b border-neutral-100 last:border-0"
                  >
                    {c.brand} {c.model}
                  </button>
                ))
              )}
              <button
                type="button"
                onClick={pickNotListed}
                className="w-full text-start px-3 py-2 text-sm text-neutral-500 hover:bg-neutral-50 border-t border-neutral-200"
              >
                {s.notListedLabel}
              </button>
            </div>
          )}
        </div>
      ) : (
        <div>
          <div className="flex items-center justify-between gap-3 mb-3">
            <span className="text-sm font-medium">{selectedLabel}</span>
            <button type="button" onClick={reset} className="text-xs text-neutral-500 underline shrink-0">
              {s.changeCamera}
            </button>
          </div>

          {verdict === "ftp" && (
            <div className="rounded-xl border border-green-200 bg-green-50 p-4">
              <p className="font-semibold text-green-900">{s.verdictFtpTitle}</p>
              <p className="text-sm text-green-800 mt-1">{s.verdictFtpBody}</p>
            </div>
          )}
          {verdict === "agent" && (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
              <p className="font-semibold text-blue-900">{s.verdictAgentTitle}</p>
              <p className="text-sm text-blue-800 mt-1">{s.verdictAgentBody}</p>
            </div>
          )}
          {verdict === "not_listed" && (
            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
              <p className="text-sm text-neutral-700">{s.verdictNotListedBody}</p>
            </div>
          )}
          {matchedNote && <p className="text-xs text-neutral-500 mt-2">{matchedNote}</p>}
        </div>
      )}

      <p className="text-xs text-neutral-500 mt-3">{s.firmwareNote}</p>
    </div>
  );
}
