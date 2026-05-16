import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

const fontSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-geist-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Confam — Clarity for markets & money",
  description:
    "Fair price guidance and safer transfer context for Nigerian shoppers — mobile-first, built for trust.",
  applicationName: "Confam",
  appleWebApp: {
    capable: true,
    title: "Confam",
    statusBarStyle: "black-translucent",
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  themeColor: "#0f3d2f",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={fontSans.variable}>
      <body className="min-h-screen bg-mist font-sans text-ink antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
