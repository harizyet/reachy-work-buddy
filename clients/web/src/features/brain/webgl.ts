/** True when the browser can create a WebGL context. Checked before any 3D code is loaded. */
export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    if (!gl) return false;
    (gl as WebGLRenderingContext).getExtension('WEBGL_lose_context')?.loseContext(); // do not hold the probe's context
    return true;
  } catch {
    return false;
  }
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export type Detail = 'low' | 'normal' | 'high';
/** Decorative particles per detail level: a ceiling, since they are only decoration. */
export const PARTICLES: Record<Detail, number> = { low: 1500, normal: 6000, high: 12000 };

/** Phones and reduced-motion users start lighter; the owner can change it. */
export function defaultDetail(width: number, reducedMotion: boolean): Detail {
  if (width < 640) return 'low';
  return reducedMotion ? 'low' : 'normal';
}
