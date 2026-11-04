import handler from '../../../../api/modulate-provider';
import adapter from '../../../../server/next-adapter.cjs';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 300;
const route = adapter.nextHandler(handler, 1100000);
export { route as GET, route as POST, route as DELETE, route as PUT, route as PATCH, route as OPTIONS, route as HEAD };
