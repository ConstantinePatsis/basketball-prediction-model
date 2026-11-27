import TodayView from "@/components/TodayView";
import { LEAGUES } from "@/lib";
export const metadata = { title: "NBA props model" };
export default function Page() { return <TodayView lg={LEAGUES.nba} />; }
