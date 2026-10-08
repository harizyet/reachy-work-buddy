// Hand-written because the hub's operator routes return bare dicts, so its
// OpenAPI document has no field-level schema for them. The parsers below check
// exactly the fields the client reads; api/samples.json (a real hub response)
// is run through them in tests, and services/reachy-hub/tests/test_web_client.py
// fails if the hub's responses stop matching that sample.
import { ApiShapeError } from './client';

export type Probe<T> = { status: 'ok'; data: T } | { status: 'unavailable' };

export interface UsageCounts {
  calls: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  avg_latency_ms: number;
  unreported_token_calls: number;
}

export interface LlmUsage {
  summary: UsageCounts;
  by_role: Partial<Record<'local' | 'cloud', UsageCounts>>;
  latest_escalation: { reason: string; at: string } | null;
}

export interface TelegramHealth {
  configured: boolean;
  healthy: boolean;
  last_poll_at: string | null;
  last_poll_error: string | null;
}

export interface RobotStatus {
  robot_id: string;
  status: 'ok' | 'unavailable';
  embodiment_state: string | null;
}

export interface HubStatus {
  hubOk: true;
  core: 'ok' | 'unavailable';
  llm: { configured: boolean | null; usage: LlmUsage | null };
  telegram: TelegramHealth;
  robots: RobotStatus[];
}

type Obj = Record<string, unknown>;

function obj(value: unknown, what: string): Obj {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ApiShapeError(what);
  return value as Obj;
}
function num(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new ApiShapeError(what);
  return value;
}
function str(value: unknown, what: string): string {
  if (typeof value !== 'string') throw new ApiShapeError(what);
  return value;
}
function bool(value: unknown, what: string): boolean {
  if (typeof value !== 'boolean') throw new ApiShapeError(what);
  return value;
}
function okOrUnavailable(value: unknown, what: string): 'ok' | 'unavailable' {
  const status = str(obj(value, what).status, `${what}.status`);
  if (status !== 'ok' && status !== 'unavailable') throw new ApiShapeError(`${what}.status`);
  return status;
}

function counts(value: unknown, what: string): UsageCounts {
  const o = obj(value, what);
  return {
    calls: num(o.calls, `${what}.calls`),
    errors: num(o.errors, `${what}.errors`),
    prompt_tokens: num(o.prompt_tokens, `${what}.prompt_tokens`),
    completion_tokens: num(o.completion_tokens, `${what}.completion_tokens`),
    avg_latency_ms: num(o.avg_latency_ms, `${what}.avg_latency_ms`),
    unreported_token_calls: num(o.unreported_token_calls, `${what}.unreported_token_calls`),
  };
}

export function parseUser(value: unknown): { username: string } {
  return { username: str(obj(value, 'auth/me').username, 'auth/me.username') };
}

export function parseStatus(value: unknown): HubStatus {
  const root = obj(value, 'status');
  const llm = obj(root.llm, 'status.llm');
  const usageProbe = obj(llm.usage, 'status.llm.usage');
  let usage: LlmUsage | null = null;
  if (okOrUnavailable(usageProbe, 'status.llm.usage') === 'ok') {
    const data = obj(usageProbe.data, 'status.llm.usage.data');
    const byRole = obj(data.by_role, 'status.llm.usage.data.by_role');
    const escalation = data.latest_escalation;
    usage = {
      summary: counts(data.summary, 'usage.summary'),
      by_role: {
        ...(byRole.local === undefined ? {} : { local: counts(byRole.local, 'usage.by_role.local') }),
        ...(byRole.cloud === undefined ? {} : { cloud: counts(byRole.cloud, 'usage.by_role.cloud') }),
      },
      latest_escalation:
        escalation == null
          ? null
          : {
              reason: str(obj(escalation, 'escalation').reason, 'escalation.reason'),
              at: str(obj(escalation, 'escalation').at, 'escalation.at'),
            },
    };
  }
  const telegram = obj(root.telegram, 'status.telegram');
  if (!Array.isArray(root.robots)) throw new ApiShapeError('status.robots');
  return {
    hubOk: true,
    core: okOrUnavailable(root.companion_core, 'status.companion_core'),
    llm: {
      configured: llm.configured === null ? null : bool(llm.configured, 'status.llm.configured'),
      usage,
    },
    telegram: {
      configured: bool(telegram.configured, 'telegram.configured'),
      healthy: bool(telegram.healthy, 'telegram.healthy'),
      last_poll_at: telegram.last_poll_at == null ? null : str(telegram.last_poll_at, 'telegram.last_poll_at'),
      last_poll_error:
        telegram.last_poll_error == null ? null : str(telegram.last_poll_error, 'telegram.last_poll_error'),
    },
    robots: root.robots.map((item, i) => {
      const robot = obj(item, `status.robots[${i}]`);
      const data = robot.data === undefined ? null : obj(robot.data, `status.robots[${i}].data`);
      const state = data?.embodiment_state;
      return {
        robot_id: str(robot.robot_id, `status.robots[${i}].robot_id`),
        status: okOrUnavailable(robot, `status.robots[${i}]`),
        embodiment_state: typeof state === 'string' ? state : null,
      };
    }),
  };
}
