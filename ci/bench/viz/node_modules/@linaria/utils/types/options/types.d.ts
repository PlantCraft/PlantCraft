import type { TransformOptions } from '@babel/core';
import type { File } from '@babel/types';
import type { IVariableContext } from '../IVariableContext';
import type { Core } from '../babel';
export declare type ClassNameSlugVars = {
    dir: string;
    ext: string;
    file: string;
    hash: string;
    name: string;
    title: string;
};
export declare type ClassNameFn = (hash: string, title: string, args: ClassNameSlugVars) => string;
export declare type VariableNameFn = (context: IVariableContext) => string;
export declare type EvaluatorConfig = {
    features: StrictOptions['features'];
    highPriorityPlugins: string[];
    onlyExports: string[];
};
export declare type Evaluator = (babelOptions: TransformOptions, ast: File, code: string, config: EvaluatorConfig, babel: Core) => [
    ast: File,
    code: string,
    imports: Map<string, string[]> | null,
    exports?: string[] | null
];
export declare type EvalRule = {
    action: Evaluator | 'ignore' | string;
    babelOptions?: TransformOptions;
    test?: RegExp | ((path: string, code: string) => boolean);
};
export declare type FeatureFlag = boolean | string | string[];
export declare type FeatureFlags = {
    dangerousCodeRemover: FeatureFlag;
};
export declare type StrictOptions = {
    babelOptions: TransformOptions;
    highPriorityPlugins: string[];
    classNameSlug?: string | ClassNameFn;
    displayName: boolean;
    evaluate: boolean;
    extensions: string[];
    features: FeatureFlags;
    ignore?: RegExp;
    rules: EvalRule[];
    tagResolver?: (source: string, tag: string) => string | null;
    variableNameConfig?: 'var' | 'dashes' | 'raw';
    variableNameSlug?: string | VariableNameFn;
};
