import type { Metadata, Viewport } from "next";
import { Tajawal } from "next/font/google";
import { LocaleProvider } from "@/components/LocaleProvider";
import "./globals.css";

// Tajawal reads well in both Arabic and Latin scripts -- one font family
// for the whole app rather than swapping fonts on locale toggle.
const tajawal = Tajawal({
  subsets: ["arabic", "latin"],
  weight: ["400", "500", "700"],
  variable: "--font-tajawal",
});

export const metadata: Metadata = {
  title: "لقطة · Laqta",
  description: "Event photo delivery — find your photos with a selfie.",
};

// Guests are on phones at a wedding hall, one-handed -- lock zoom out so
// double-tap/pinch never fights the camera-capture UI, and let the layout
// account for iOS Safari's dynamic toolbar via 100dvh instead of 100vh.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // dir/lang default to Arabic/RTL for the server-rendered markup --
  // LocaleProvider switches them client-side after mount if the visitor
  // has an English preference stored. See components/LocaleProvider.tsx.
  return (
    <html lang="ar" dir="rtl" className={tajawal.variable}>
      <body className="min-h-[100dvh] bg-neutral-50 font-sans text-neutral-900 antialiased">
        <LocaleProvider>{children}</LocaleProvider>
      </body>
    </html>
  );
}
