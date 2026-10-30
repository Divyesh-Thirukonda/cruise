import handler from '../../../../api/modulate-discovery';
import adapter from '../../../../server/next-adapter.cjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 30;
const route = adapter.nextHandler(handler, 1024);
export { route as GET, route as POST };
