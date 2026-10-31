"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.EventEmitter = void 0;
class EventEmitter {
  static dummy = new EventEmitter(() => {});
  constructor(onEvent) {
    this.onEvent = onEvent;
  }
  pair(labels) {
    this.onEvent(labels, 'start');
    return () => {
      this.onEvent(labels, 'finish');
    };
  }
  single(labels) {
    this.onEvent(labels, 'single');
  }
}
exports.EventEmitter = EventEmitter;
//# sourceMappingURL=EventEmitter.js.map