import handler from '../../../../api/modulate';
import adapter from '../../../../server/next-adapter.cjs';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 30;
const route = adapter.nextHandler(handler);
export { route as GET, route as POST, route as DELETE, route as PUT, route as PATCH, route as OPTIONS, route as HEAD };
