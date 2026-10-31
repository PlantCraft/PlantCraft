import type { CallExpression, Expression, ObjectExpression, SourceLocation } from '@babel/types';
import type { Params, Rules, TailProcessorParams, ValueCache, WrappedNode } from '@linaria/tags';
import { TaggedTemplateProcessor } from '@linaria/tags';
import type { IVariableContext } from '@linaria/utils';
export interface IProps {
    atomic?: boolean;
    class?: string;
    name: string;
    propsAsIs: boolean;
    vars?: Record<string, Expression[]>;
}
export default class StyledProcessor extends TaggedTemplateProcessor {
    #private;
    component: WrappedNode;
    constructor(params: Params, ...args: TailProcessorParams);
    addInterpolation(node: Expression, precedingCss: string, source: string, unit?: string): string;
    doEvaltimeReplacement(): void;
    doRuntimeReplacement(): void;
    extractRules(valueCache: ValueCache, cssText: string, loc?: SourceLocation | null): Rules;
    get asSelector(): string;
    protected get tagExpressionArgument(): Expression;
    protected get tagExpression(): CallExpression;
    get value(): ObjectExpression;
    toString(): string;
    protected getCustomVariableId(source: string, unit: string, precedingCss: string): string | undefined;
    protected getProps(): IProps;
    protected getTagComponentProps(props: IProps): ObjectExpression;
    protected getVariableContext(source: string, unit: string, precedingCss: string): IVariableContext;
    protected getVariableId(source: string, unit: string, precedingCss: string): string;
}
