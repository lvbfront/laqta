import type { HelpContent } from "@/app/help/camera/content";

function Box({ children, tone = "default" }: { children: React.ReactNode; tone?: "default" | "accent" }) {
  return (
    <div
      className={`rounded-2xl border px-4 py-3 text-center text-sm font-medium w-full max-w-xs ${
        tone === "accent" ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 bg-white"
      }`}
    >
      {children}
    </div>
  );
}

function Arrow({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center text-neutral-400">
      {label && <span className="text-xs text-neutral-500 mb-0.5">{label}</span>}
      {/* Always a vertical flow -- a downward arrow needs no RTL
          mirroring the way a horizontal one would, and it sidesteps
          the real overflow problem a 6-box horizontal row hit at
          ordinary page widths with full-length Arabic labels. */}
      <span className="text-lg leading-none">↓</span>
    </div>
  );
}

// Always a vertical, single-column flow -- reads top to bottom in both
// directions, no RTL-specific handling needed (unlike a horizontal row,
// where mirroring an arrow glyph and worrying about overflow at
// realistic page widths both become real problems).
export function FlowDiagram({ content }: { content: HelpContent }) {
  const d = content.diagram;
  return (
    <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4 sm:p-6">
      <div className="flex flex-col items-center gap-1.5 mx-auto w-fit">
        <Box>{d.camera}</Box>
        <Arrow label={d.usbCable} />
        <Box>{d.tetheringSoftware}</Box>
        <Arrow />
        <Box tone="accent">{d.folder}</Box>
        <Arrow label={d.watches} />
        <Box>{d.agent}</Box>
        <Arrow label={d.uploads} />
        <Box>{d.laqta}</Box>
      </div>
    </div>
  );
}
