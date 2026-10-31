import {probe} from './probe';

// @ts-ignore
if (!globalThis.probe) {
  // @ts-ignore
  globalThis.probe = probe;
}
