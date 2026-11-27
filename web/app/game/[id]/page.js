import GameView from "@/components/GameView";
import { LEAGUES } from "@/lib";
export function generateStaticParams() { return (LEAGUES.el.slate.games || []).map((g) => ({ id: g.id })); }
export default async function Page({ params }) { const { id } = await params; return <GameView lg={LEAGUES.el} id={id} />; }
