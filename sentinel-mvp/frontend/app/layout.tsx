import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sentinel — Self-Healing Agent Monitor",
  description: "Detect, diagnose, and heal agent memory leaks.",
};

// Next.js App Router requires a default export for the root layout.
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
