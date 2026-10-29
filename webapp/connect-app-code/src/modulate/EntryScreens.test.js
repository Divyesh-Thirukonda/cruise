import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { Camera, Settings2 } from 'lucide-react';
import { AccessStep, SetupScreen } from './EntryScreens';

const choices = [
  { key: 'system', title: 'System controls', detail: 'Adjust system settings.', icon: Settings2 },
  { key: 'camera', title: 'Mac camera', detail: 'Use the paired camera.', icon: Camera },
];

function props() {
  return {
    navigate: jest.fn(), onSave: jest.fn(), onDismissNotice: jest.fn(),
    permissions: { system: true, camera: true }, choices, online: true,
  };
}

test('polled revocations update untouched choices and saving sends only the explicit edit', () => {
  const initial = props();
  const { rerender } = render(<AccessStep {...initial} />);
  fireEvent.click(screen.getByRole('switch', { name: 'Allow system controls' }));

  rerender(<AccessStep {...initial} permissions={{ system: true, camera: false }} />);

  expect(screen.getByRole('switch', { name: 'Allow mac camera' })).toHaveAttribute('aria-checked', 'false');
  expect(screen.getByRole('switch', { name: 'Allow system controls' })).toHaveAttribute('aria-checked', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Save & open Studio' }));
  expect(initial.onSave).toHaveBeenCalledTimes(1);
  expect(initial.onSave).toHaveBeenCalledWith({ system: false });
});

test('saving without edits never writes a stale grant after a polled revocation', () => {
  const initial = props();
  const { rerender } = render(<AccessStep {...initial} />);
  rerender(<AccessStep {...initial} permissions={{ system: true, camera: false }} />);

  fireEvent.click(screen.getByRole('button', { name: 'Save & open Studio' }));
  expect(initial.onSave).not.toHaveBeenCalled();
  expect(initial.navigate).toHaveBeenCalledWith('studio');
});

test('keeping current access discards unsaved edits without changing device grants', () => {
  const initial = props();
  render(<AccessStep {...initial} />);
  fireEvent.click(screen.getByRole('switch', { name: 'Allow system controls' }));
  fireEvent.click(screen.getByRole('button', { name: 'Keep current access' }));

  expect(initial.onSave).not.toHaveBeenCalled();
  expect(initial.navigate).toHaveBeenCalledWith('studio');
});


test('setup returns to the website connection flow without modifying access', () => {
  const navigate = jest.fn();
  render(<SetupScreen navigate={navigate} connected={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Return to connection' }));
  expect(navigate).toHaveBeenCalledWith('connect');
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
});
