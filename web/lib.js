import slate from "@/data/slate.json";
import results from "@/data/results.json";
import backtest from "@/data/backtest.json";
import updated from "@/data/updated_at.json";
import nbaSlate from "@/data/nba_slate.json";
import nbaResults from "@/data/nba_results.json";
import nbaBacktest from "@/data/nba_backtest.json";
export { slate, results, backtest, updated, nbaSlate, nbaResults, nbaBacktest };
export const pct = (x) => (x == null ? "–" : `${Math.round(100 * x)}%`);
export const gap = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(Math.round(100 * x))}`);
export const ev = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(Math.round(100 * x))}%`);
export const eur = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}€${Math.abs(x).toFixed(2)}`);
export const mins = (l) => (l.expected_minutes == null ? "–" : `${Math.round(l.expected_minutes)}${l.min_low != null ? ` (${Math.round(l.min_low)}–${Math.round(l.min_high)})` : ""}`);
export const side = (s) => (s === "OVER" ? "Over" : "Under");
export const tz = { timeZone: "Europe/Athens" };
export const time = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...tz }) : "");
export const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", ...tz }) : "");
export const stamp = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...tz }) : "");
export const LEAGUES = {
  el: { base: "", name: "EuroLeague", slate, results, backtest },
  nba: { base: "/nba", name: "NBA", slate: nbaSlate, results: nbaResults, backtest: nbaBacktest },
};
