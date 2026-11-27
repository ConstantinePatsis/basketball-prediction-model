import GameView from "@/components/GameView";
import { LEAGUES } from "@/lib";
export function generateStaticParams() { return (LEAGUES.nba.slate.games || []).map((g) => ({ id: g.id })); }
export default async function Page({ params }) { const { id } = await params; return <GameView lg={LEAGUES.nba} id={id} />; }
