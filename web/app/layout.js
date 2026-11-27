import "./globals.css";
import Link from "next/link";
import { updated, stamp } from "@/lib";
import Nav from "@/components/Nav";
export const metadata = { title: "Player props model", robots: { index: false, follow: false } };
export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;700&display=swap" rel="stylesheet" />
      </head>
      <body>
        <header className="bar-top"><div className="in">
          <Link href="/" className="logo">Props <b>model</b></Link>
          <Nav />
          <span className="stamp">Updated {stamp(updated)}</span>
        </div></header>
        <main>{children}</main>
      </body>
    </html>
  );
}
