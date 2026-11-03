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
  expect(checkApp(app, ['display'])).toMatch(/Attach buttons/);
  expect(checkApp(app, ['display', 'buttons'])).toBeNull();
});
