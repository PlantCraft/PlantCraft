import type { BigIntLiteral, BooleanLiteral, DecimalLiteral, Identifier, NullLiteral, NumericLiteral, StringLiteral } from '@babel/types';
export declare type Artifact = [name: string, data: unknown];
export declare type JSONValue = null | string | number | boolean | JSONObject | JSONArray;
export interface JSONObject {
    [x: string]: JSONValue;
}
export declare type JSONArray = Array<JSONValue>;
export declare type Serializable = JSONValue;
export declare type BuildCodeFrameErrorFn = <TError extends Error>(msg: string, Error?: new (msg: string) => TError) => TError;
export declare enum ValueType {
    LAZY = 0,
    FUNCTION = 1,
    CONST = 2
}
export declare type LazyValue = {
    buildCodeFrameError: BuildCodeFrameErrorFn;
    ex: Identifier;
    importedFrom?: string[];
    kind: ValueType.LAZY;
    source: string;
};
export declare type FunctionValue = {
    buildCodeFrameError: BuildCodeFrameErrorFn;
    ex: Identifier;
    importedFrom?: string[];
    kind: ValueType.FUNCTION;
    source: string;
};
export declare type ConstValue = {
    buildCodeFrameError: BuildCodeFrameErrorFn;
    ex: StringLiteral | NumericLiteral | NullLiteral | BooleanLiteral | BigIntLiteral | DecimalLiteral;
    kind: ValueType.CONST;
    source: string;
    value: string | number | boolean | null;
};
export declare type ExpressionValue = LazyValue | FunctionValue | ConstValue;
export declare type StyledMeta = {
    __linaria: {
        className: string;
        extends: StyledMeta;
    };
};
export declare type Location = {
    line: number;
    column: number;
};
export interface ICSSRule {
    className: string;
    displayName: string;
    cssText: string;
    start: Location | null | undefined;
    atom?: boolean;
}
export declare type Rules = Record<string, ICSSRule>;
export declare type LinariaMetadata = {
    processors: {
        artifacts: Artifact[];
    }[];
    rules: Rules;
    replacements: Replacement[];
    dependencies: string[];
};
export declare type Replacement = {
    original: {
        start: Location;
        end: Location;
    };
    length: number;
};
export declare type Replacements = Array<Replacement>;
export interface IEvaluatorMetadata {
    imports: Map<string, string[]>;
}
export interface IMetadata {
    linariaEvaluator: IEvaluatorMetadata;
}
