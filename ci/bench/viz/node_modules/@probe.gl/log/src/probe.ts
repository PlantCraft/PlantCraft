import {isBrowser, process, window} from '@probe.gl/env';

export class Probe {
  markdown?: boolean;
  priority?: number;

  getHighResolutionTimer(): number {
    let timestamp;
    if (isBrowser() && window.performance) {
      timestamp = window?.performance?.now?.();
    } else if ('hrtime' in process) {
      // @ts-ignore
      const timeParts = process?.hrtime?.();
      timestamp = timeParts[0] * 1000 + timeParts[1] / 1e6;
    } else {
      timestamp = Date.now();
    }
    return timestamp;
  }

  getMemoryUsageMB(): number | null {
    const performance = window?.performance as {
      memory?: {
        usedJSHeapSize?: number | null;
      };
    };
    const usedJSHeapSize = performance?.memory?.usedJSHeapSize;
    if (usedJSHeapSize === undefined || usedJSHeapSize === null) {
      return null;
    }
    return Math.trunc(usedJSHeapSize / 1024 / 1024);
  }
}

export const probe = new Probe();

(globalThis as typeof globalThis & {Probe: typeof Probe}).Probe = Probe;
(globalThis as typeof globalThis & {probe: typeof probe}).probe = probe;
