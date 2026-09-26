import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "GridTwin",
  description: "Fault-tolerant VPP dispatch orchestrator",
};

const NAV_LINKS = [
  { href: "/live", label: "Live" },
  { href: "/data", label: "Data" },
  { href: "/insights", label: "Insights" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased min-h-screen">
        <div className="mx-auto flex min-h-screen max-w-6xl flex-col">
          <header className="flex items-center gap-6 border-b border-slate-800 px-6 py-4">
            <span className="text-lg font-semibold tracking-tight">GridTwin</span>
            <nav className="flex gap-4 text-sm">
              {NAV_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-slate-400 transition-colors hover:text-slate-100"
                >
                  {link.label}
                </Link>
              ))}
            </nav>
          </header>
          <main className="flex-1 px-6 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
