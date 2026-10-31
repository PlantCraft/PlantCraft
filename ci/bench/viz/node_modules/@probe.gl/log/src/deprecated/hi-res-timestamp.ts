// probe.gl, MIT license

import {probe} from '../probe';

/** Get best timer available. */
/**
 * @deprecated Use probe.getHighResolutionTimer() instead.
 */
export function getHiResTimestamp() {
  return probe.getHighResolutionTimer();
}
