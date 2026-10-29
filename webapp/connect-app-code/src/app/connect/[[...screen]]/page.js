import { redirect } from 'next/navigation';

const screens = new Set(['setup', 'access', 'studio', 'library', 'permissions', 'activity', 'code', 'device']);

export default async function ConnectPage({ params }) {
  const { screen = [] } = await params;
  if (screen.length > 1 || (screen.length === 1 && !screens.has(screen[0]))) redirect('/connect');
  // The persistent Connect layout keeps polling and draft state across routes.
  return null;
}
