import { BaseSchemes } from 'rete';
import { RenderPreset } from '../types';
import { ContextMenuRender, Customize } from './types';
export { ItemStyle as Item, SubitemStyles as Subitems } from './components/Item';
export { Styles as Menu } from './components/Menu';
export { SearchInput as Search } from './components/Search';
export { CommonStyle as Common } from './styles';
type Props = {
    delay?: number;
    customize?: Customize;
};
/**
 * Preset for rendering context menu.
 */
export declare function setup<Schemes extends BaseSchemes, K extends ContextMenuRender>(props?: Props): RenderPreset<Schemes, K>;
//# sourceMappingURL=index.d.ts.map