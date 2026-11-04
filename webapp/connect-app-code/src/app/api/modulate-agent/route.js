import handler from '../../../../api/modulate-agent';
import adapter from '../../../../server/next-adapter.cjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 30;
const route = adapter.nextHandler(handler, 20000);
export { route as GET, route as POST, route as DELETE, route as OPTIONS };
