import './globals.css';

export const metadata = {
  title: 'Modulate — Give your hardware a new idea',
  description: 'Connect your Modulate, then make games, apps and useful controls by speaking.',
};
export const viewport = { themeColor: '#101113' };
// Nonces are generated for each response, so HTML must never be prerendered.
export const dynamic = 'force-dynamic';

export default function RootLayout({ children }) {
  return <html lang="en"><body>{children}</body></html>;
}
