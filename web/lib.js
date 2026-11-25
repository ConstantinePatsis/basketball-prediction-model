import slate from "@/data/slate.json";
import results from "@/data/results.json";
import backtest from "@/data/backtest.json";
import updated from "@/data/updated_at.json";
export { slate, results, backtest, updated };
export const pct = (x, d = 0) => (x == null ? "–" : `${(100 * x).toFixed(d)}%`);
export const eur = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}€${Math.abs(x).toFixed(2)}`);
export const when = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Athens" }) : "");
