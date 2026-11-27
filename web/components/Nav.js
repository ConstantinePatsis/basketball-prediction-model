"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
export default function Nav() {
  const path = usePathname() || "/";
  const nba = path.startsWith("/nba");
  const b = nba ? "/nba" : "";
  const here = (href) => (path === href || (href !== b && href !== "/" && path.startsWith(href)) ? "on" : undefined);
  return (<>
    <div className="league" role="tablist" aria-label="League">
      <Link href="/" className={!nba ? "on" : undefined} aria-current={!nba ? "page" : undefined}>EuroLeague</Link>
      <Link href="/nba" className={nba ? "on" : undefined} aria-current={nba ? "page" : undefined}>NBA</Link>
    </div>
    <nav>
      <Link href={b || "/"} className={path === (b || "/") ? "on" : undefined}>Today</Link>
      <Link href={`${b}/results`} className={here(`${b}/results`)}>Results</Link>
      <Link href={`${b}/backtest`} className={here(`${b}/backtest`)}>Backtest</Link>
      <Link href="/about" className={here("/about")}>How it works</Link>
    </nav>
  </>);
}
