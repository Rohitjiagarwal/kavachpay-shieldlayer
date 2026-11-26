import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "KavachPay · protected by ShieldLayer",
  description: "KavachPay: a UPI support assistant guarded by ShieldLayer, a 4-layer prompt-injection defence. Live demo and recorded attack replays.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
