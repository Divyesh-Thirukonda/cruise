import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import Demo from './Demo';
import { freshWorkspace, STORAGE_KEY } from './model';

beforeEach(() => { localStorage.clear(); jest.useFakeTimers(); global.fetch = jest.fn(() => { throw new Error('Demo must never contact the live API'); }); });
afterEach(() => { jest.useRealTimers(); delete global.fetch; });
const request = text => { fireEvent.change(screen.getByRole('textbox', { name: 'Demo request' }), { target: { value: text } }); fireEvent.click(screen.getByRole('button', { name: 'Try request' })); };
const finishBuild = () => { for (let i = 0; i < 3; i++) act(() => { jest.advanceTimersByTime(500); }); };

test('a visitor can make, persist and restore an example without any live API calls', () => {
  const first = render(<Demo />);
  request('make a pink racing game');
  finishBuild();
  expect(screen.getByRole('heading', { name: 'Pixel Rally' })).toBeInTheDocument();
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
  expect(saved.apps).toHaveLength(4);
  expect(saved.apps.find(a => a.id === saved.activeId)).toMatchObject({ kind: 'rally', color: 'pink' });
  fireEvent.click(screen.getByRole('button', { name: 'Restore previous app' }));
  expect(screen.getByRole('heading', { name: 'Orbit Catch' })).toBeInTheDocument();
  first.unmount();
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: /App library/ }));
  expect(screen.getAllByRole('heading', { name: 'Pixel Rally' })).toHaveLength(2);
  expect(global.fetch).not.toHaveBeenCalled();
});

test('cancelled and unmounted walkthroughs never activate a late app', () => {
  const rendered = render(<Demo />);
  request('make a racing game');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  finishBuild();
  expect(screen.getByRole('heading', { name: 'Orbit Catch' })).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(3);
  request('make a synthesizer');
  rendered.unmount();
  finishBuild();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(3);
});

test('disconnecting all steering inputs pauses play and rejects activation', () => {
  render(<Demo />);
  fireEvent.click(screen.getByRole('button', { name: 'Play game' }));
  fireEvent.click(screen.getByRole('button', { name: 'Remove joystick' }));
  expect(screen.getByRole('button', { name: 'Pause', exact: true })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Remove rotary knob' }));
  expect(screen.getByRole('button', { name: 'Play game' })).toBeDisabled();
  request('make a racing game');
  finishBuild();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).apps).toHaveLength(3);
  fireEvent.click(screen.getByRole('button', { name: 'Attach rotary knob' }));
  expect(screen.getByRole('button', { name: 'Play game' })).toBeEnabled();
});

test('unsupported requests preserve the current app and library', () => {
  render(<Demo />);
  request('read my email');
  expect(screen.getByText(/Open-ended Meta generation/)).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY))).toEqual(freshWorkspace());
  expect(global.fetch).not.toHaveBeenCalled();
});

test('unavailable browser storage still permits a session-only demo', () => {
  const get = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  const set = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  render(<Demo />);
  expect(screen.getByText(/Session only/)).toBeInTheDocument();
  request('make a racing game');
  finishBuild();
  expect(screen.getByRole('heading', { name: 'Pixel Rally' })).toBeInTheDocument();
  get.mockRestore(); set.mockRestore();
});
