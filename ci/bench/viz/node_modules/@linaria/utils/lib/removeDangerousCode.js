"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.removeDangerousCode = void 0;
var _findIdentifiers = require("./findIdentifiers");
var _isUnnecessaryReactCall = _interopRequireDefault(require("./isUnnecessaryReactCall"));
var _scopeHelpers = require("./scopeHelpers");
var _JSXElementsRemover = _interopRequireDefault(require("./visitors/JSXElementsRemover"));
function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }
const isGlobal = id => {
  if (!(0, _findIdentifiers.nonType)(id)) {
    return false;
  }
  const {
    scope
  } = id;
  const {
    name
  } = id.node;
  return !scope.hasBinding(name) && scope.hasGlobal(name);
};
const forbiddenGlobals = new Set(['XMLHttpRequest', 'clearImmediate', 'clearInterval', 'clearTimeout', 'document', 'fetch', 'localStorage', 'location', 'navigator', 'sessionStorage', 'setImmediate', 'setInterval', 'setTimeout', 'window']);
const isBrowserGlobal = id => {
  return forbiddenGlobals.has(id.node.name) && isGlobal(id);
};
const getPropertyName = path => {
  if (path.isIdentifier()) {
    return path.node.name;
  }
  if (path.isStringLiteral()) {
    return path.node.value;
  }
  return null;
};
const removeDangerousCode = programPath => {
  programPath.traverse({
    // JSX can be replaced with a dummy value,
    // but we have to do it after we processed template tags.
    CallExpression: {
      enter(p) {
        if ((0, _isUnnecessaryReactCall.default)(p)) {
          (0, _JSXElementsRemover.default)(p);
        }
      }
    },
    JSXElement: {
      enter: _JSXElementsRemover.default
    },
    JSXFragment: {
      enter: _JSXElementsRemover.default
    },
    MemberExpression(p, state) {
      const obj = p.get('object');
      const prop = p.get('property');
      if (!obj.isIdentifier({
        name: 'window'
      })) {
        return;
      }
      const name = getPropertyName(prop);
      if (!name) {
        return;
      }
      state.windowScoped.add(name);
      // eslint-disable-next-line no-param-reassign
      state.globals = state.globals.filter(id => {
        if (id.node.name === name) {
          (0, _scopeHelpers.removeWithRelated)([id]);
          return false;
        }
        return true;
      });
    },
    MetaProperty(p) {
      // Remove all references to `import.meta`
      (0, _scopeHelpers.removeWithRelated)([p]);
    },
    Identifier(p, state) {
      if (p.find(parent => parent.isTSTypeReference())) {
        // don't mess with TS type references
        return;
      }
      if (isBrowserGlobal(p)) {
        if (p.find(parentPath => parentPath.isUnaryExpression({
          operator: 'typeof'
        }) || parentPath.isTSTypeQuery())) {
          // Ignore `typeof window` expressions
          return;
        }
        if (p.parentPath.isClassProperty()) {
          // ignore class property decls
          return;
        }
        if (p.parentPath.isMemberExpression() && p.key === 'property') {
          // ignore e.g this.fetch()
          // window.fetch will be handled by the windowScoped block below
          return;
        }
        (0, _scopeHelpers.removeWithRelated)([p]);
        return;
      }
      if (state.windowScoped.has(p.node.name)) {
        (0, _scopeHelpers.removeWithRelated)([p]);
      } else if (isGlobal(p)) {
        state.globals.push(p);
      }
    }
  }, {
    globals: [],
    windowScoped: new Set()
  });
};
exports.removeDangerousCode = removeDangerousCode;
//# sourceMappingURL=removeDangerousCode.js.map