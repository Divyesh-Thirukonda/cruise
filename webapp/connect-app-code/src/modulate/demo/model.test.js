import { checkApp, freshWorkspace, restoreWorkspace } from './model';
const app = {
  id: 'a'.repeat(64),
  title: 'Counter',
  description: 'Test fixture',
  requires: ['display', 'buttons'],
  controls: { buttons: 'A increments' },
  code: 'function init(){return 0}function update(s){return s}function draw(){return []}',
  inference: { model: 'muse-spark-1.3' },
};
test('browser library rejects legacy presets and malformed packages', () => {
  expect(freshWorkspace().apps).toEqual([]);
  expect(restoreWorkspace(JSON.stringify({ version: 1, apps: [{ kind: 'rally' }] }))).toEqual(
    freshWorkspace(),
  );
  const w = {
    ...freshWorkspace(),
    apps: [app, { ...app, id: 'bad' }],
    modules: ['display', 'shell'],
    activeId: app.id,
  };
  expect(restoreWorkspace(JSON.stringify(w))).toMatchObject({
    apps: [app],
    modules: ['display'],
    activeId: app.id,
  });
});
test('removing a required component blocks saved-app activation', () => {
  expect(checkApp(app, ['display'])).toBe('Attach the action buttons to run this app.');
  expect(checkApp(app, ['display', 'buttons'])).toBeNull();
});

test('version 2 workspaces keep their apps and gain the sensor and virtual computer once', () => {
  const v2 = { version: 2, modules: ['display', 'buttons'], apps: [app], activeId: app.id };
  const restored = restoreWorkspace(JSON.stringify(v2));
  expect(restored).toMatchObject({ version: 3, apps: [{ ...app, favorite: false }] });
  expect(restored.modules).toEqual(['display', 'buttons', 'imu', 'computer']);
  expect(restored.hardware).toEqual({ imuDriver: 'ready', extraButton: null });
});
