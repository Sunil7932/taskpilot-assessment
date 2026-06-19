import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "TaskPilot Dashboard",
  description: "Monitor and create background tasks.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b bg-white">
          <div className="mx-auto max-w-5xl px-4 py-4">
            <h1 className="text-xl font-semibold">TaskPilot</h1>
            <p className="text-sm text-slate-500">Background-job dashboard</p>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
