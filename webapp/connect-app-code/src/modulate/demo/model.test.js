import { checkApp, freshWorkspace, interpretRequest, newGame, restoreWorkspace, stepGame } from './model';

test('restores only bounded, valid browser-owned app state', () => {
  const workspace = freshWorkspace();
  workspace.apps[0].title = 'My little game';
  workspace.modules = ['display', 'encoder', 'shell'];
  expect(restoreWorkspace(JSON.stringify(workspace)).modules).toEqual(['display', 'encoder']);
  expect(restoreWorkspace(JSON.stringify(workspace)).apps[0].title).toBe('My little game');
  for (const input of ['not json', JSON.stringify({ ...workspace, activeId: 'missing' }), JSON.stringify({ ...workspace, apps: [{ ...workspace.apps[0], color: '__proto__' }] }), JSON.stringify({ ...workspace, apps: Array(25).fill(workspace.apps[0]) }), JSON.stringify({ ...workspace, apps: [{ ...workspace.apps[0], speed: 500 }] })]) {
    expect(restoreWorkspace(input)).toEqual(freshWorkspace());
  }
});

test('apps require actual demo capabilities and support the alternative steering input', () => {
  const { apps } = freshWorkspace();
  expect(checkApp(apps[0], ['display', 'encoder'])).toBe('');
  expect(checkApp(apps[0], ['display'])).toMatch(/joystick or rotary knob/);
  expect(checkApp(apps[0], ['encoder'])).toMatch(/display/);
  expect(checkApp(apps[2], ['display', 'encoder'])).toMatch(/speaker/);
});

test('request examples preserve current edits and reject unsupported requests', () => {
  const current = freshWorkspace().apps[0];
  expect(interpretRequest('make a pink racing game faster', current)).toMatchObject({ kind: 'rally', color: 'pink', speed: 1.5 });
  expect(interpretRequest('make it slower', current)).toMatchObject({ kind: 'orbit', speed: 0.7 });
  expect(interpretRequest('open my email and control the Mac', current)).toBeNull();
});

test('star catches score once, misses lose a life, and the game ends at zero', () => {
  const app = freshWorkspace().apps[0];
  const initial = { ...newGame(), objects: [{ id: 1, x: 120, y: 107 }] };
  const caught = stepGame(initial, 0.05, 0, app);
  expect(caught.score).toBe(10);
  expect(stepGame(caught, 0.05, 0, app).score).toBe(10);
  const missed = stepGame({ ...initial, x: 30, lives: 1 }, 0.05, 0, app);
  expect(missed.lives).toBe(0);
  expect(stepGame(missed, 0.05, 1, app)).toBe(missed);
});

test('racer collisions cost a life and steering remains on the screen', () => {
  const app = freshWorkspace().apps[1];
  const hit = stepGame({ ...newGame(), objects: [{ id: 1, x: 120, y: 107 }] }, 0.05, 0, app);
  expect(hit.lives).toBe(2);
  expect(stepGame({ ...newGame(), x: 213 }, 0.05, 1, app).x).toBe(214);
});
