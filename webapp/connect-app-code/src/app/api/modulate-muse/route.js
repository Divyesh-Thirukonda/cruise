import handler from '../../../../api/modulate-muse';
import adapter from '../../../../server/next-adapter.cjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 30;
const route = adapter.nextHandler(handler, 16384);
export { route as GET, route as POST, route as DELETE, route as OPTIONS };
