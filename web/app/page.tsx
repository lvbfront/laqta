import Link from "next/link";

// Not one of the three specified routes -- just enough of a landing page
// that `/` isn't a 404. Guests always arrive via /e/[qr_token] from a
// printed QR code, never here.
export default function HomePage() {
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 p-6 text-center">
      <h1 className="text-3xl font-bold">لقطة · Laqta</h1>
      <p className="max-w-sm text-neutral-600">
        Scan an event&apos;s QR code to find your photos, or open the organizer dashboard below.
      </p>
      <Link
        href="/dashboard/events"
        className="rounded-full bg-neutral-900 px-6 py-3 text-white font-medium active:scale-95 transition"
      >
        Organizer dashboard
      </Link>
    </main>
  );
}
