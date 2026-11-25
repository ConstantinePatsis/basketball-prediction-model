import "./globals.css";
import Link from "next/link";
import { updated, when } from "@/lib";
export const metadata = { title: "EuroLeague player-prop model", robots: { index: false, follow: false } };
export default function RootLayout({ children }) {
  return (
    <html lang="en"><body>
      <header className="top"><div className="in">
        <div className="brand">EuroLeague <span>model</span></div>
        <nav><Link href="/">Today</Link><Link href="/results">Results</Link><Link href="/backtest">Backtest</Link><Link href="/about">How it works</Link></nav>
        <div className="updated">Updated {when(updated)}</div>
      </div></header>
      <main>{children}</main>
    </body></html>
  );
}
