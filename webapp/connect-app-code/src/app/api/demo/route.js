import { demoHandler } from '../../../../server/demo-api.mjs';
export const runtime = 'nodejs';
export const maxDuration = 300;
export const dynamic = 'force-dynamic';
export const GET = demoHandler();
export const POST = GET;
