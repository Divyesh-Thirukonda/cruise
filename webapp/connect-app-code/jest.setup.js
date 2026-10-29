import '@testing-library/jest-dom';

jest.mock('next/navigation', () => {
  const router = { push: jest.fn(), replace: jest.fn(), refresh: jest.fn() };
  return { usePathname: jest.fn(() => '/connect/studio'), useRouter: () => router };
});
