import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Phishpicker",
  description: "Real-time Phish setlist prediction",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Phishpicker",
    // black-translucent lets the status bar float over our dark bg rather
    // than eat a band for the clock; matches the full-bleed app look.
    statusBarStyle: "black-translucent",
  },
  icons: {
    apple: "/apple-touch-icon.png",
  },
};

// viewportFit=cover extends layout under the iOS safe areas; themeColor
// tints Safari's address bar + bottom chrome to match the app background.
export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark h-full bg-neutral-950 text-neutral-100 antialiased`}
    >
      <body className="min-h-full flex flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
        {children}
      </body>
    </html>
  );
}
