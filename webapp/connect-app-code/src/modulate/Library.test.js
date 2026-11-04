import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import AppLibrary from './Library';

const now = Date.now();
const game = { id: 'a'.repeat(64), title: 'Moon Racer', kind: 'game', favorite: false, trashed: false, active: true, protected: true };
const favorite = { id: 'b'.repeat(64), title: 'Focus Clock', kind: 'app', favorite: true, trashed: false };
const trashed = { id: 'c'.repeat(64), title: 'Old Dodger', kind: 'game', trashed: true };
const confirmation = { id: 'single-use-confirmation', entry_id: trashed.id, title: trashed.title, expires_at: (now + 60000) / 1000 };
const entries = [game, favorite, trashed];
const base = { library: { items: entries, view: { open: false } }, disabled: false, running: false, deviceConnected: true, now };

test('browsing and filtering does not change the device; opening uses a saved id', () => {
  const onAction = jest.fn();
  render(<AppLibrary {...base} onAction={onAction} />);
  expect(screen.getByRole('article', { name: game.title })).toBeInTheDocument();
  expect(screen.queryByRole('article', { name: trashed.title })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Favorites/ }));
  expect(screen.queryByRole('article', { name: game.title })).not.toBeInTheDocument();
  expect(onAction).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole('article', { name: favorite.title })).getByRole('button', { name: 'Open', exact: true }));
  expect(onAction).toHaveBeenCalledWith('library', '/api/library', { action: 'launch', entry_id: favorite.id }, undefined);
});

test('favorites are explicit and trashing a running app is distinct from permanent deletion', () => {
  const onAction = jest.fn();
  render(<AppLibrary {...base} onAction={onAction} />);
  fireEvent.click(screen.getByRole('button', { name: 'Favorite Moon Racer' }));
  expect(onAction).toHaveBeenLastCalledWith('library', '/api/library', { action: 'favorite', entry_id: game.id, favorite: true }, undefined);
  fireEvent.click(screen.getByRole('button', { name: 'Move Moon Racer to Trash' }));
  expect(onAction).toHaveBeenLastCalledWith('library', '/api/library', { action: 'trash', entry_id: game.id }, expect.stringContaining('current running app is unchanged'));
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
});

test('permanent deletion requires a fresh server confirmation and a second named action', async () => {
  const onAction = jest.fn().mockResolvedValue({ purge_confirmation: confirmation });
  render(<AppLibrary {...base} onAction={onAction} />);
  fireEvent.click(screen.getByRole('button', { name: /Trash 1/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete forever' }));
  const dialog = await screen.findByRole('alertdialog');
  expect(within(dialog).getByRole('heading')).toHaveTextContent('Old Dodger');
  expect(onAction.mock.calls.map(call => call[2].action)).toEqual(['purge']);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Permanently delete' }));
  await waitFor(() => expect(onAction).toHaveBeenLastCalledWith('library', '/api/library', { action: 'confirm_purge', entry_id: trashed.id, confirmation_id: confirmation.id }, 'App permanently deleted.'));
});

test('protected trash can be restored but cannot be permanently deleted', () => {
  const onAction = jest.fn();
  render(<AppLibrary {...base} library={{ entries: [{ ...game, trashed: true }] }} onAction={onAction} />);
  fireEvent.click(screen.getByRole('button', { name: /Trash 1/ }));
  expect(screen.getByRole('button', { name: 'Delete forever' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Restore' }));
  expect(onAction).toHaveBeenCalledWith('library', '/api/library', { action: 'restore', entry_id: game.id }, expect.any(String));
});

test('expired confirmations and a device that goes offline cannot launch or delete', () => {
  const onAction = jest.fn();
  const { rerender } = render(<AppLibrary {...base} library={{ entries, purge_confirmation: { ...confirmation, expires_at: (now - 1000) / 1000 } }} onAction={onAction} />);
  expect(screen.getByRole('button', { name: 'Permanently delete' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Permanently delete' }));
  expect(onAction).not.toHaveBeenCalled();
  rerender(<AppLibrary {...base} disabled deviceConnected={false} library={{ entries, purge_confirmation: null }} onAction={onAction} />);
  expect(screen.getByRole('button', { name: 'Show on device' })).toBeDisabled();
  screen.getAllByRole('button', { name: 'Open', exact: true }).forEach(button => expect(button).toBeDisabled());
});


test('device menu uses the selected view and server-cleared confirmation disappears', async () => {
  const onAction = jest.fn().mockResolvedValue({ ok: true });
  const { rerender } = render(<AppLibrary {...base} onAction={onAction} />);
  fireEvent.click(screen.getByRole('button', { name: /Favorites/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Show on device' }));
  expect(onAction).toHaveBeenCalledWith('library', '/api/library', { action: 'open', tab: 'favorites' }, undefined);
  rerender(<AppLibrary {...base} library={{ items: entries, view: { open: true }, purge_confirmation: confirmation }} onAction={onAction} />);
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  rerender(<AppLibrary {...base} library={{ items: entries, view: { open: true }, purge_confirmation: null }} onAction={onAction} />);
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Return to app' }));
  expect(onAction).toHaveBeenLastCalledWith('library', '/api/library', { action: 'close', tab: 'favorites' }, undefined);
});

test('while building, library mutations wait but the device menu can close', () => {
  const onAction = jest.fn();
  const { rerender } = render(<AppLibrary {...base} running library={{ items: entries, view: { open: true } }} onAction={onAction} />);
  expect(screen.getByRole('button', { name: 'Favorite Moon Racer' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Move Moon Racer to Trash' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Return to app' }));
  expect(onAction).toHaveBeenLastCalledWith('library', '/api/library', { action: 'close', tab: 'all' }, undefined);
  rerender(<AppLibrary {...base} running library={{ items: entries, view: { open: true }, purge_confirmation: confirmation }} onAction={onAction} />);
  expect(screen.getByRole('button', { name: 'Permanently delete' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Keep in Trash' })).toBeEnabled();
});

test('earlier revisions are retained but hidden until requested', () => {
  const older = { ...game, id: 'd'.repeat(64), latest: false, active: false };
  render(<AppLibrary {...base} library={{ items: [{ ...game, latest: true }, older] }} onAction={jest.fn()} />);
  expect(screen.getAllByRole('article', { name: game.title })).toHaveLength(1);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Show earlier saved versions' }));
  expect(screen.getAllByRole('article', { name: game.title })).toHaveLength(2);
});
