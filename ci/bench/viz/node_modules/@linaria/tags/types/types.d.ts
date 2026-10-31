import type { Expression, Identifier, TemplateElement, MemberExpression } from '@babel/types';
import type { ExpressionValue, Location, StyledMeta } from '@linaria/utils';
export declare type CSSPropertyValue = string | number;
export declare type ObjectWithSelectors = {
    [key: string]: ObjectWithSelectors | CSSPropertyValue | (ObjectWithSelectors | CSSPropertyValue)[];
};
export declare type CSSable = ObjectWithSelectors[string];
export declare type Value = (() => void) | StyledMeta | CSSable;
export declare type ValueCache = Map<string | number | boolean | null, unknown>;
export interface ICSSRule {
    atom?: boolean;
    className: string;
    cssText: string;
    displayName: string;
    start: Location | null | undefined;
}
export interface IInterpolation {
    id: string;
    node: Expression;
    source: string;
    unit: string;
}
export declare type WrappedNode = string | {
    node: Identifier;
    nonLinaria?: true;
    source: string;
};
export declare type Rules = Record<string, ICSSRule>;
export declare type CalleeParam = readonly ['callee', Identifier | MemberExpression];
export declare type CallParam = readonly ['call', ...ExpressionValue[]];
export declare type MemberParam = readonly ['member', string];
export declare type TemplateParam = readonly [
    'template',
    (TemplateElement | ExpressionValue)[]
];
export declare type Param = CalleeParam | CallParam | MemberParam | TemplateParam;
export declare type Params = readonly Param[];
