import { describe, expect, it } from 'vitest';
import samples from '../src/api/samples.json';
import { ApiShapeError } from '../src/api/client';
import { parseStatus, parseUser } from '../src/api/types';

// samples.json is a real hub response; test_web_client.py keeps it in step with the hub.
describe('response parsers', () => {
  it('accept the real hub sample', () => {
    expect(parseUser(samples.auth_me)).toEqual({ username: 'owner' });
    const status = parseStatus(samples.status);
    expect(status.core).toBe('ok');
    expect(status.llm.configured).toBe(true);
    expect(status.llm.usage?.summary.calls).toBe(0);
    expect(status.robots).toEqual([{ robot_id: 'desk', status: 'ok', embodiment_state: 'idle' }]);
    expect(status.telegram.configured).toBe(false);
  });

  it('handle degraded sections the hub reports as unavailable', () => {
    const degraded = {
      ...samples.status,
      companion_core: { status: 'unavailable' },
      llm: { status: 'unavailable', configured: null, usage: { status: 'unavailable' } },
      robots: [{ robot_id: 'desk', status: 'unavailable' }],
    };
    const status = parseStatus(degraded);
    expect(status.core).toBe('unavailable');
    expect(status.llm).toEqual({ configured: null, usage: null });
    expect(status.robots[0]?.embodiment_state).toBeNull();
  });

  it('reject a response that lost a field the client reads', () => {
    const { telegram: _telegram, ...broken } = samples.status;
    expect(() => parseStatus(broken)).toThrow(ApiShapeError);
    expect(() => parseUser({})).toThrow(ApiShapeError);
    expect(() => parseStatus(null)).toThrow(ApiShapeError);
  });
});
