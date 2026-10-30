# PlantCraft brand kit

Everything needed to show PlantCraft outside the product: logos, app marks, colours and the
social media images. The rules for using them are in [`docs/brand.md`](../docs/brand.md); the
interface takes the same values from [`ui/src/tokens.css`](../ui/src/tokens.css).

<img src="../docs/images/logo.svg" alt="PlantCraft" width="300">

## Logo

The letters P and C drawn as a control valve on a process line.

| File | Use |
| --- | --- |
| [`docs/images/logo.svg`](../docs/images/logo.svg), [`logo-dark.svg`](../docs/images/logo-dark.svg) | Lockup (mark + name) on light and dark backgrounds |
| [`docs/images/logo-mark.svg`](../docs/images/logo-mark.svg) | Mark alone (also the favicon) |
| [`logo/plantcraft-logo-1200.png`](logo/plantcraft-logo-1200.png), [`logo/plantcraft-logo-dark-1200.png`](logo/plantcraft-logo-dark-1200.png) | Lockup as PNG, transparent background (slides, documents) |
| [`logo/plantcraft-mark-1024.png`](logo/plantcraft-mark-1024.png), `-512`, `-180` | Mark as PNG (app icons, profile pictures) |
| [`docs/images/social.png`](../docs/images/social.png) | Link preview, 1200 x 630 |
| [`docs/images/apps/`](../docs/images/apps/) | One mark per app, plus `family.svg` and `family-dark.svg` |

## Colours

| Name | Light | Dark | Use |
| --- | --- | --- | --- |
| Steel Blue | `#2E5A88` | `#3D78B6` | The brand colour: logo tile, buttons, selection |
| Steel Blue text | `#2B5582` | `#7FA6D1` | Links and accents as text; on black always the light value `#7FA6D1` |
| Selection | `#E8EEF5` | `#1C2A3B` | Selected rows, active tabs |
| Ink | `#0B0D10` | | Dark backgrounds for marketing (site, LinkedIn, video) |
| Graphite | `#1B1E23` | | Sidebar and dark panels |
| Slate | `#5B6270` | | Secondary text on light |
| Mist | `#F3F4F6` | | Light backgrounds |

App tile colours (white glyph on top) are listed in [`docs/brand.md`](../docs/brand.md#palette).
Status colours (good, attention, problem...) are for plant states only, never for decoration.

## Type

Inter for everything (headlines tighter, -2% letter spacing), JetBrains Mono for tags, ids and
numbers. Both ship with the suite in [`ui/src/fonts/`](../ui/src/fonts/).

## Social media

| File | Use |
| --- | --- |
| [`social/avatar-400.png`](social/avatar-400.png) | Profile picture (LinkedIn, GitHub, YouTube, X) |
| [`social/banner-1128x191@3x.png`](social/banner-1128x191@3x.png) | LinkedIn page banner; text on the right so the page logo never covers it |
| [`social/x-header-1500x500.png`](social/x-header-1500x500.png) | X (Twitter) header |
| [`social/youtube-banner-2560x1440.png`](social/youtube-banner-2560x1440.png) | YouTube banner; the text sits inside the 1546 x 423 area every device shows |

Marketing pieces are dark: Ink background, white text, Steel Blue text value `#7FA6D1` as the
only colour, and real screens of the plant as the image.

## Regenerating

The marks come from [`ui/src/appMarks.ts`](../ui/src/appMarks.ts). After a change:
`node --experimental-strip-types ui/src/appMarks.render.mjs` (from `ui/`), then
`python3 dev/brand-logos` from the repository root. The PNGs here are exports of those files.
