"use client";

import Link from "next/link";
import { useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { LocaleToggle } from "@/components/LocaleToggle";
import { FlowDiagram } from "@/components/help/FlowDiagram";
import { CONTENT } from "./content";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-xl font-bold mb-4">{title}</h2>
      {children}
    </section>
  );
}

function TroubleshootingItem({ question, answer }: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-start font-medium"
        aria-expanded={open}
      >
        <span>{question}</span>
        <span className="text-neutral-400 shrink-0">{open ? "−" : "+"}</span>
      </button>
      {open && <p className="px-4 pb-4 text-sm leading-relaxed text-neutral-600">{answer}</p>}
    </div>
  );
}

export default function CameraHelpPage() {
  const { locale } = useLocale();
  const content = CONTENT[locale];

  return (
    <div className="min-h-[100dvh] p-4 sm:p-8">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <Link href="/dashboard/events" className="text-sm text-neutral-500 underline">
            {locale === "ar" ? "رجوع إلى الفعاليات" : "Back to events"}
          </Link>
          <LocaleToggle />
        </div>

        <h1 className="text-2xl sm:text-3xl font-bold mb-8">{content.pageTitle}</h1>

        {/* Lead with the two-layer relationship -- the single most common
            point of confusion, per the brief this page was written from. */}
        <section className="rounded-2xl border-2 border-neutral-900 bg-white p-5">
          <h2 className="text-lg font-bold mb-3">{content.intro.heading}</h2>
          <div className="flex flex-col gap-3 text-sm leading-relaxed text-neutral-700">
            {content.intro.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
          </div>
        </section>

        <div className="mt-6">
          <FlowDiagram content={content} />
        </div>

        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <div className="rounded-2xl border border-neutral-200 bg-white p-4">
            <h3 className="font-semibold mb-1">{content.usbNote.title}</h3>
            <p className="text-sm text-neutral-600 leading-relaxed">{content.usbNote.body}</p>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
            <h3 className="font-semibold mb-1 text-amber-900">{content.eosWarning.title}</h3>
            <p className="text-sm text-amber-800 leading-relaxed">{content.eosWarning.body}</p>
          </div>
        </div>

        <Section title={content.vendorsHeading}>
          <div className="grid gap-3 sm:grid-cols-2">
            {content.vendors.map((v) => (
              <a
                key={v.brand}
                href={v.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-2xl border border-neutral-200 bg-white p-4 hover:border-neutral-400 transition"
              >
                <p className="font-semibold">
                  {v.brand} — {v.software}
                </p>
                <p className="text-sm text-neutral-500 mt-1">{v.urlLabel} ↗</p>
                {v.note && <p className="text-xs text-neutral-500 mt-2">{v.note}</p>}
              </a>
            ))}
          </div>
        </Section>

        <Section title={content.stepsHeading}>
          <ol className="flex flex-col gap-4">
            {content.steps.map((step, i) => (
              <li key={i} className="flex gap-3">
                <span className="shrink-0 flex items-center justify-center h-7 w-7 rounded-full bg-neutral-900 text-white text-sm font-semibold">
                  {i + 1}
                </span>
                <div>
                  <p className="font-medium">{step.title}</p>
                  <p className="text-sm text-neutral-600 mt-0.5 leading-relaxed">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </Section>

        <Section title={content.troubleshootingHeading}>
          <div className="flex flex-col gap-2">
            {content.troubleshooting.map((qa, i) => (
              <TroubleshootingItem key={i} question={qa.question} answer={qa.answer} />
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}
