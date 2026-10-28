"""A report as one HTML page: the file to download and what a report's public link shows.

Everything is inside the page (styles, the script, the data), so it opens offline, from an email
or a USB stick, and asks nothing of the network. The headings of the text cells make the side
navigation (it marks where the reader is); charts are drawn by the page's own small script, with
a crosshair that reads every line at the moment under the pointer (Grafana's hover) and a legend
that hides and shows lines. Without the script a chart still shows its table of values. Every text
that comes from data is escaped; the data of a chart is JSON inside a ``<script type=
"application/json">``, with ``<`` escaped so it never closes the tag.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from dashcraft.i18n import t
from dashcraft.reports import markdown as md
from dashcraft.reports.document import CardPart, Document, Part, Table

MEDIA_TYPE = "text/html; charset=utf-8"


def _spans(spans: list[md.Span]) -> str:
    out = []
    for span in spans:
        text = escape(span.text)
        if span.style == "bold":
            out.append(f"<strong>{text}</strong>")
        elif span.style == "italic":
            out.append(f"<em>{text}</em>")
        elif span.style == "code":
            out.append(f"<code>{text}</code>")
        elif span.style == "link":
            external = span.href.lower().startswith(("http://", "https://"))
            attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
            out.append(f'<a href="{escape(span.href)}"{attrs}>{text}</a>')
        else:
            out.append(text)
    return "".join(out)


def _table(table: Table, cls: str = "rc-table") -> str:
    head = "".join(
        f'<th class="rc-{(table.align[i] if i < len(table.align) else "left") or "left"}">'
        f"{escape(text)}</th>"
        for i, text in enumerate(table.head)
    )
    rows = []
    for index, row in enumerate(table.rows):
        state = table.states[index] if index < len(table.states) else ""
        cells = "".join(
            f'<td class="rc-{(table.align[i] if i < len(table.align) else "left") or "left"}">'
            f"{_spans(cell) if isinstance(cell, list) else escape(str(cell))}</td>"
            for i, cell in enumerate(row)
        )
        rows.append(f'<tr class="{f"rc-row-{state}" if state else ""}">{cells}</tr>')
    return (
        f'<div class="rc-table-wrap"><table class="{cls}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _blocks(blocks: list[md.Block]) -> str:
    out = []
    for block in blocks:
        if block.kind == "heading":
            level = min(block.level + 1, 5)
            out.append(f'<h{level} id="{escape(block.anchor)}">{_spans(block.spans)}</h{level}>')
        elif block.kind == "paragraph":
            out.append(f"<p>{_spans(block.spans)}</p>")
        elif block.kind == "quote":
            out.append(f"<blockquote>{_spans(block.spans)}</blockquote>")
        elif block.kind == "rule":
            out.append("<hr>")
        elif block.kind == "list":
            tag = "ol" if block.numbered else "ul"
            items = "".join(f"<li>{_spans(item)}</li>" for item in block.items)
            out.append(f"<{tag}>{items}</{tag}>")
        elif block.kind == "table":
            out.append(
                _table(
                    Table(
                        head=[md.plain(cell) for cell in block.head],
                        rows=block.rows,  # type: ignore[arg-type]
                        align=block.align,
                    )
                )
            )
    return "".join(out)


def _json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _chart(part: CardPart, zone: str) -> str:
    data = {
        "scatter": part.show == "scatter",
        "zone": zone,
        "start": part.start,
        "end": part.end,
        "thresholds": [[value, color] for value, color in part.thresholds],
        "series": [
            {
                "label": item.label,
                "unit": item.unit,
                "color": item.color,
                "right": item.right,
                "t": item.times,
                "v": item.values,
            }
            for item in part.series
        ],
    }
    legend = _table(part.legend, "rc-table rc-legend") if part.legend is not None else ""
    fallback = (
        _table(
            Table(
                head=[t("Signal"), t("Min"), t("Mean"), t("Max"), t("Last")],
                rows=[
                    [
                        item.label,
                        item.stats["min"],
                        item.stats["mean"],
                        item.stats["max"],
                        item.stats["last"],
                    ]
                    for item in part.series
                ],  # fmt: skip
                align=["left", "right", "right", "right", "right"],
            )
        )
        if part.show == "scatter"
        else ""
    )
    return (
        f'<div class="rc-chart" role="img" aria-label="{escape(part.title or t("Chart"))}">'
        f'<script type="application/json">{_json(data)}</script></div>'
        f"<noscript>{fallback}</noscript>{legend}"
    )


def _tiles(part: CardPart) -> str:
    out = []
    for tile in part.tiles:
        meter = (
            f'<span class="rc-meter"><i style="width:{round(tile.share * 100, 1)}%"></i></span>'
            if tile.share is not None
            else ""
        )
        unit = f" <small>{escape(tile.unit)}</small>" if tile.unit else ""
        detail = (
            f'<span class="rc-tile-detail{" rc-problem" if tile.error else ""}">'
            f"{escape(tile.detail)}</span>"
            if tile.detail
            else ""
        )
        out.append(
            f'<div class="rc-tile rc-state-{escape(tile.state)}"><span class="rc-tile-label">'
            f"{escape(tile.label)}</span><b>{escape(tile.value)}{unit}</b>{meter}{detail}</div>"
        )
    return f'<div class="rc-tiles">{"".join(out)}</div>'


def _bars(part: CardPart) -> str:
    numbers = [bar.value for bar in part.bars if bar.value is not None]
    high = max([abs(n) for n in numbers] + [0.0]) or 1.0
    rows = []
    for bar in part.bars:
        share = 0.0 if bar.value is None else abs(bar.value) / high * 100
        rows.append(
            f'<div class="rc-bar"><span>{escape(bar.label)}</span><span class="rc-bar-track">'
            f'<i style="width:{share:.1f}%;background:{escape(bar.color)}"></i></span>'
            f"<b>{escape(bar.text)}</b></div>"
        )
    return f'<div class="rc-bars">{"".join(rows)}</div>'


def _card(part: CardPart, zone: str) -> str:
    out = []
    if part.title:
        out.append(f"<h4>{escape(part.title)}</h4>")
    if part.description:
        out.append(f'<p class="rc-note">{escape(part.description)}</p>')
    if part.show == "empty":
        out.append(f'<div class="rc-empty">{escape(part.empty)}</div>')
    elif part.show in ("chart", "scatter"):
        out.append(_chart(part, zone))
    elif part.show == "tiles":
        out.append(_tiles(part))
    elif part.show == "bars":
        out.append(_bars(part))
    elif part.show == "table" and part.table is not None:
        out.append(_table(part.table))
    out.extend(f'<p class="rc-note">{escape(note)}</p>' for note in part.notes)
    out.extend(f'<p class="rc-note rc-problem">{escape(text)}</p>' for text in part.problems)
    return "".join(out)


def _events(part: Part) -> str:
    out = [f"<h4>{escape(part.title)}</h4>"]
    if part.error:
        out.append(f'<p class="rc-note rc-problem">{escape(part.error)}</p>')
        return "".join(out)
    if part.counts:
        out.append(f'<p class="rc-note">{escape(part.counts)}</p>')
    if part.empty:
        out.append(f'<div class="rc-empty">{escape(part.empty)}</div>')
    elif part.table is not None:
        out.append(_table(part.table))
    if part.note:
        out.append(f'<p class="rc-note">{escape(part.note)}</p>')
    return "".join(out)


def _parts(document: Document, zone: str) -> str:
    out: list[str] = []
    parts = document.parts
    index = 0
    while index < len(parts):
        part = parts[index]
        if part.kind == "break":
            out.append('<div class="rc-break" aria-hidden="true"></div>')
            index += 1
            continue
        pair = (
            part.half
            and index + 1 < len(parts)
            and parts[index + 1].half
            and parts[index + 1].kind in ("card", "events")
        )
        group = parts[index : index + 2] if pair else [part]
        cells = []
        for item in group:
            if item.kind == "text":
                body = _blocks(item.blocks)
            elif item.kind == "card" and item.card is not None:
                body = _card(item.card, zone)
            else:
                body = _events(item)
            cells.append(f'<section class="rc-cell rc-is-{item.kind}">{body}</section>')
        out.append(f'<div class="rc-pair">{"".join(cells)}</div>' if pair else cells[0])
        index += 2 if pair else 1
    if not parts:
        out.append(f'<p class="rc-note">{escape(t("This report has no sections yet."))}</p>')
    return "".join(out)


def _outline(document: Document) -> str:
    if not document.outline:
        return ""
    items = "".join(
        f'<li class="rc-l{heading.level}"><a href="#{escape(heading.anchor)}">'
        f"{escape(heading.text)}</a></li>"
        for heading in document.outline
    )
    return (
        f'<nav class="rc-outline" aria-label="{escape(t("Sections"))}"><details open><summary>'
        f"{escape(t('Sections'))}</summary><ol>{items}</ol></details></nav>"
    )


def render(document: Document, zone: str | None, *, live: bool = False) -> str:
    """The page of ``document`` (``document.build``); ``live`` for a public link (it says the
    report was read when the page was opened, and offers the reader to read it again)."""

    meta = "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
        for label, value in document.meta
        if value
    )
    problems = (
        f'<p class="rc-note rc-problem">{escape(document.problems)}</p>'
        if document.problems
        else ""
    )
    again = (
        f'<a class="rc-again" href="">{escape(t("Read again"))}</a>' if live else ""
    )  # a link to the page itself: the browser reads the report anew
    words = {
        "hide": t("Click to hide or show this line"),
    }
    return (
        "<!doctype html>"
        f'<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="generator" content="PlantCraft View">'
        '<meta name="robots" content="noindex">'
        f"<title>{escape(document.name)}</title><style>{CSS}</style></head><body>"
        f'<div class="rc-shell{" rc-has-outline" if document.outline else ""}">'
        f"{_outline(document)}"
        f'<main class="rc-paper"><header class="rc-cover">'
        f'<span class="rc-eyebrow">{escape(t("PlantCraft View · Report"))}</span>'
        f"<h1>{escape(document.name)}</h1>"
        + (f'<p class="rc-lead">{escape(document.description)}</p>' if document.description else "")
        + f'<dl class="rc-meta">{meta}</dl>{problems}{again}</header>'
        f"{_parts(document, zone or 'UTC')}"
        f'<footer class="rc-foot">{escape(t("Made by PlantCraft View on {made}.", made=document.made))}'
        "</footer></main></div>"
        f'<script type="application/json" id="rc-words">{_json(words)}</script>'
        f"<script>{SCRIPT}</script></body></html>"
    )


CSS = """
:root{--ink:#1d1d1f;--text2:#424245;--muted:#6e6e73;--grid:#e8e8ed;--axis:#d2d2d7;--pale:#f5f5f7;
--paper:#fff;--page:#f5f5f7;--brand:#3442a6;--ok:#1f8f3f;--warning:#b86e00;--alarm:#d92d20;
--warn-bg:#fff4e5;--alarm-bg:#fdecea;--link:#1762b6;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--ink:#f5f5f7;--text2:#d2d2d7;--muted:#98989d;
--grid:#2c2c2e;--axis:#3a3a3c;--pale:#1c1c1e;--paper:#111113;--page:#000;--brand:#8e9bff;
--ok:#32d74b;--warning:#ffb340;--alarm:#ff6961;--warn-bg:#3a2a10;--alarm-bg:#3b1715;--link:#64a8ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 -apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
a{color:var(--link)}
.rc-shell{max-width:1180px;margin:0 auto;padding:24px 16px 48px;display:grid;gap:24px}
.rc-has-outline{grid-template-columns:220px minmax(0,1fr)}
.rc-outline{position:sticky;top:16px;align-self:start;max-height:calc(100vh - 32px);overflow:auto;
font-size:13px}
.rc-outline summary{font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;
font-size:11px;cursor:pointer;margin-bottom:6px}
.rc-outline ol{list-style:none;margin:0;padding:0;border-left:1px solid var(--axis)}
.rc-outline li a{display:block;padding:3px 10px;color:var(--text2);text-decoration:none;
border-left:2px solid transparent;margin-left:-1px}
.rc-outline li a:hover{color:var(--ink)}
.rc-outline li a.rc-here{color:var(--brand);border-left-color:var(--brand);font-weight:600}
.rc-outline .rc-l2 a{padding-left:20px}.rc-outline .rc-l3 a{padding-left:30px;font-size:12px}
.rc-outline .rc-l4 a{padding-left:40px;font-size:12px}
.rc-paper{background:var(--paper);border-radius:14px;padding:36px 44px;min-width:0;
box-shadow:0 1px 3px rgba(0,0,0,.06)}
.rc-cover{border-bottom:1px solid var(--axis);padding-bottom:16px;margin-bottom:8px}
.rc-eyebrow{color:var(--brand);font-weight:700;font-size:11px;letter-spacing:.08em;
text-transform:uppercase}
.rc-cover h1{margin:4px 0 2px;font-size:30px;line-height:1.2}
.rc-lead{color:var(--text2);margin:4px 0 0}
.rc-meta{display:flex;flex-wrap:wrap;gap:8px 28px;margin:16px 0 0}
.rc-meta dt{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.rc-meta dd{margin:0;font-weight:600;font-size:13px}
.rc-again{display:inline-block;margin-top:10px;font-size:13px}
h2,h3,h4,h5{scroll-margin-top:16px;line-height:1.25}
h2{font-size:23px;margin:30px 0 8px}h3{font-size:19px;margin:24px 0 6px}
h4{font-size:16px;margin:20px 0 6px}h5{font-size:14px;margin:16px 0 4px}
.rc-cell{margin:14px 0;min-width:0}
.rc-pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.rc-note{color:var(--muted);font-size:12.5px;margin:2px 0 6px}
.rc-problem{color:var(--alarm)}
blockquote{margin:8px 0;padding:2px 14px;border-left:3px solid var(--axis);color:var(--text2)}
code{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--pale);
padding:1px 4px;border-radius:4px}
hr{border:0;border-top:1px solid var(--axis);margin:18px 0}
.rc-table-wrap{overflow-x:auto}
.rc-table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
.rc-table th{color:var(--muted);font-weight:600;font-size:12px;text-align:left;
border-bottom:1px solid var(--axis);padding:5px 8px}
.rc-table td{border-bottom:1px solid var(--grid);padding:5px 8px;vertical-align:top}
.rc-table .rc-right{text-align:right}.rc-table .rc-center{text-align:center}
.rc-row-warning td{background:var(--warn-bg)}.rc-row-alarm td{background:var(--alarm-bg)}
.rc-legend{margin-top:6px;font-size:12.5px}
.rc-legend tr{cursor:pointer}.rc-legend tr.rc-off td{opacity:.4}
.rc-legend td:first-child:before{content:"";display:inline-block;width:12px;height:3px;
border-radius:2px;margin-right:8px;vertical-align:middle;background:var(--c,var(--muted))}
.rc-empty{background:var(--pale);color:var(--muted);border-radius:8px;padding:16px;
text-align:center;font-size:13px}
.rc-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.rc-tile{background:var(--pale);border-radius:8px;padding:10px 12px;border-left:3px solid var(--axis);
display:flex;flex-direction:column;gap:2px}
.rc-tile b{font-size:24px;font-variant-numeric:tabular-nums;line-height:1.2}
.rc-tile small{font-size:13px;color:var(--muted);font-weight:400}
.rc-tile-label{font-size:12px;color:var(--text2)}
.rc-tile-detail{font-size:11.5px;color:var(--muted)}
.rc-state-ok{border-left-color:var(--ok)}.rc-state-ok b{color:var(--ok)}
.rc-state-warning{border-left-color:var(--warning)}.rc-state-warning b{color:var(--warning)}
.rc-state-alarm{border-left-color:var(--alarm)}.rc-state-alarm b{color:var(--alarm)}
.rc-meter{height:5px;background:var(--grid);border-radius:3px;overflow:hidden;margin:4px 0}
.rc-meter i{display:block;height:100%;background:currentColor;color:var(--brand)}
.rc-state-ok .rc-meter i{color:var(--ok)}.rc-state-warning .rc-meter i{color:var(--warning)}
.rc-state-alarm .rc-meter i{color:var(--alarm)}
.rc-bars{display:grid;gap:6px;font-size:13px}
.rc-bar{display:grid;grid-template-columns:minmax(80px,32%) 1fr auto;gap:10px;align-items:center}
.rc-bar span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2)}
.rc-bar-track{height:12px;background:var(--grid);border-radius:3px;overflow:hidden}
.rc-bar-track i{display:block;height:100%}
.rc-bar b{font-variant-numeric:tabular-nums;font-weight:600}
.rc-chart{position:relative;width:100%;height:260px;touch-action:pan-y}
.rc-chart svg{display:block;width:100%;height:100%;overflow:visible}
.rc-chart text{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.rc-chart .rc-gl{stroke:var(--grid);stroke-width:1}.rc-chart .rc-ax{stroke:var(--axis)}
.rc-chart .rc-x{stroke:var(--muted);stroke-dasharray:3 3;stroke-width:1}
.rc-tip{position:absolute;pointer-events:none;background:var(--paper);color:var(--ink);
border:1px solid var(--axis);border-radius:8px;padding:7px 9px;font-size:12px;
box-shadow:0 4px 14px rgba(0,0,0,.14);white-space:nowrap;z-index:2;min-width:150px}
.rc-tip b{display:block;margin-bottom:3px;font-size:11.5px;color:var(--muted);font-weight:600}
.rc-tip div{display:flex;gap:10px;justify-content:space-between;align-items:center}
.rc-tip i{display:inline-block;width:10px;height:3px;border-radius:2px;margin-right:6px;
vertical-align:middle}
.rc-tip span:last-child{font-variant-numeric:tabular-nums;font-weight:600}
.rc-break{border-top:1px dashed var(--axis);margin:24px 0}
.rc-foot{margin-top:36px;padding-top:10px;border-top:1px solid var(--grid);color:var(--muted);
font-size:12px}
@media (max-width:860px){.rc-has-outline{grid-template-columns:1fr}.rc-outline{position:static;
max-height:none}.rc-paper{padding:22px 18px}.rc-pair{grid-template-columns:1fr}}
@media print{body{background:#fff}.rc-outline,.rc-again{display:none}.rc-shell{display:block;
padding:0}.rc-paper{box-shadow:none;padding:0}.rc-break{border:0;break-after:page}
.rc-cell{break-inside:avoid}}
"""

# The page's own script: each chart is drawn into an SVG from its JSON, again when the page is
# resized; hovering reads every line at that moment (as Grafana's shared tooltip does).
SCRIPT = r"""
(function(){
var words={};try{words=JSON.parse(document.getElementById('rc-words').textContent);}catch(e){}
var NS='http://www.w3.org/2000/svg';
function el(name,attrs,parent){var n=document.createElementNS(NS,name);for(var k in attrs)n.setAttribute(k,attrs[k]);if(parent)parent.appendChild(n);return n;}
function num(v){if(v==null||!isFinite(v))return'–';var a=Math.abs(v),d=a>=1000?0:a>=100?1:a>=1?2:3;if(v===Math.round(v)&&a<1e15)d=0;return v.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});}
function ticks(lo,hi,n){if(!isFinite(lo)||!isFinite(hi))return[0,1];if(hi<=lo){var s=Math.abs(lo)*.1||1;lo-=s;hi+=s;}var raw=(hi-lo)/n,p=Math.pow(10,Math.floor(Math.log10(raw))),st=[1,2,2.5,5,10].map(function(f){return f*p;}).filter(function(x){return x>=raw;})[0],out=[],v=Math.floor(lo/st)*st;while(v<=hi+st*.5&&out.length<20){out.push(+v.toFixed(10));v+=st;}if(out[out.length-1]<hi)out.push(+(out[out.length-1]+st).toFixed(10));return out;}
function timeFmt(zone,span){var o=span>2*86400e3?{month:'short',day:'numeric'}:{hour:'2-digit',minute:'2-digit',hour12:false};try{return new Intl.DateTimeFormat('en-GB',Object.assign({timeZone:zone},o));}catch(e){return new Intl.DateTimeFormat('en-GB',o);}}
function fullFmt(zone){var o={day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false};try{return new Intl.DateTimeFormat('en-GB',Object.assign({timeZone:zone},o));}catch(e){return new Intl.DateTimeFormat('en-GB',o);}}
function draw(box,d,off){
 box.innerHTML='';box.appendChild(d._json);
 var W=box.clientWidth||600,H=box.clientHeight||260,L=48,B=24,T=8,R=d.series.some(function(s){return s.right;})?48:12;
 var pw=W-L-R,ph=H-B-T,svg=el('svg',{viewBox:'0 0 '+W+' '+H,width:W,height:H},box);
 var shown=d.series.filter(function(s,i){return !off[i];});
 if(d.scatter){drawScatter(box,svg,d,W,H,L,B,T,R);return;}
 function vals(right){var a=[];shown.forEach(function(s){if(!!s.right===right)s.v.forEach(function(v){if(v!=null)a.push(v);});});return a;}
 var lv=vals(false),rv=vals(true);if(!lv.length&&rv.length){lv=rv;rv=[];}
 d.thresholds.forEach(function(th){if(lv.length){var lo=Math.min.apply(null,lv),hi=Math.max.apply(null,lv),sp=(hi-lo)||1;if(th[0]>=lo-sp*.3&&th[0]<=hi+sp*.3)lv.push(th[0]);}});
 var yt=ticks(lv.length?Math.min.apply(null,lv):0,lv.length?Math.max.apply(null,lv):1,5),y0=yt[0],y1=yt[yt.length-1];
 var rt=rv.length?ticks(Math.min.apply(null,rv),Math.max.apply(null,rv),5):null;
 var x0=d.start,x1=d.end;if(!(x1>x0)){x0=Infinity;x1=-Infinity;d.series.forEach(function(s){s.t.forEach(function(t){x0=Math.min(x0,t);x1=Math.max(x1,t);});});}
 function X(t){return L+(t-x0)/((x1-x0)||1)*pw;}
 function Y(v,right){if(right&&rt)return T+ph-(v-rt[0])/((rt[rt.length-1]-rt[0])||1)*ph;return T+ph-(v-y0)/((y1-y0)||1)*ph;}
 yt.forEach(function(v){var y=Y(v);el('line',{x1:L,x2:L+pw,y1:y,y2:y,'class':'rc-gl'},svg);el('text',{x:L-6,y:y+4,'text-anchor':'end'},svg).textContent=num(v);});
 if(rt)rt.forEach(function(v){el('text',{x:L+pw+6,y:Y(v,true)+4},svg).textContent=num(v);});
 el('line',{x1:L,x2:L+pw,y1:T+ph,y2:T+ph,'class':'rc-ax'},svg);
 var span=x1-x0,fmt=timeFmt(d.zone,span),n=Math.max(2,Math.min(8,Math.floor(pw/90)));
 for(var i=0;i<=n;i++){var t=x0+span*i/n,x=X(t);el('line',{x1:x,x2:x,y1:T+ph,y2:T+ph+4,'class':'rc-ax'},svg);el('text',{x:x,y:H-6,'text-anchor':i===0?'start':i===n?'end':'middle'},svg).textContent=fmt.format(new Date(t));}
 d.thresholds.forEach(function(th){if(th[0]>=y0&&th[0]<=y1){var y=Y(th[0]);el('line',{x1:L,x2:L+pw,y1:y,y2:y,stroke:th[1],'stroke-dasharray':'5 4','stroke-width':1.2},svg);}});
 d.series.forEach(function(s,i){if(off[i])return;var p='',pen=false;for(var k=0;k<s.t.length;k++){var v=s.v[k];if(v==null){pen=false;continue;}p+=(pen?'L':'M')+X(s.t[k]).toFixed(1)+' '+Y(v,s.right).toFixed(1);pen=true;}
  el('path',{d:p,fill:'none',stroke:s.color,'stroke-width':1.6,'stroke-linejoin':'round','stroke-linecap':'round'},svg);});
 var cross=el('line',{y1:T,y2:T+ph,'class':'rc-x',visibility:'hidden'},svg),dots=shown.map(function(s){return el('circle',{r:3.5,fill:s.color,style:'stroke:var(--paper)','stroke-width':1.5,visibility:'hidden'},svg);});
 var tip=document.createElement('div');tip.className='rc-tip';tip.style.display='none';box.appendChild(tip);var full=fullFmt(d.zone);
 function near(s,t){var lo=0,hi=s.t.length-1;if(hi<0)return -1;while(hi-lo>1){var m=(lo+hi)>>1;if(s.t[m]<t)lo=m;else hi=m;}return Math.abs(s.t[lo]-t)<=Math.abs(s.t[hi]-t)?lo:hi;}
 function move(ev){var r=svg.getBoundingClientRect(),px=(ev.touches?ev.touches[0].clientX:ev.clientX)-r.left;if(px<L||px>L+pw){hide();return;}
  var t=x0+(px-L)/pw*(x1-x0),rows='';cross.setAttribute('x1',px);cross.setAttribute('x2',px);cross.setAttribute('visibility','visible');
  shown.forEach(function(s,i){var k=near(s,t),v=k<0?null:s.v[k];if(v==null){dots[i].setAttribute('visibility','hidden');}else{dots[i].setAttribute('cx',X(s.t[k]));dots[i].setAttribute('cy',Y(v,s.right));dots[i].setAttribute('visibility','visible');}
   rows+='<div><span><i style="background:'+s.color+'"></i>'+esc(s.label)+'</span><span>'+num(v)+(s.unit&&v!=null?' '+esc(s.unit):'')+'</span></div>';});
  tip.innerHTML='<b>'+esc(full.format(new Date(t)))+'</b>'+rows;tip.style.display='block';var tw=tip.offsetWidth;tip.style.left=(px+14+tw>W?px-14-tw:px+14)+'px';tip.style.top=T+'px';}
 function hide(){cross.setAttribute('visibility','hidden');dots.forEach(function(c){c.setAttribute('visibility','hidden');});tip.style.display='none';}
 svg.addEventListener('mousemove',move);svg.addEventListener('touchmove',move,{passive:true});svg.addEventListener('mouseleave',hide);
}
function drawScatter(box,svg,d,W,H,L,B,T,R){
 if(d.series.length<2)return;var a=d.series[0],b=d.series[1],pts=[];for(var k=0;k<Math.min(a.v.length,b.v.length);k++)if(a.v[k]!=null&&b.v[k]!=null)pts.push([a.v[k],b.v[k],a.t[k]]);if(!pts.length)return;
 var pw=W-L-R,ph=H-B-T,xs=pts.map(function(p){return p[0];}),ys=pts.map(function(p){return p[1];}),xt=ticks(Math.min.apply(null,xs),Math.max.apply(null,xs),6),yt=ticks(Math.min.apply(null,ys),Math.max.apply(null,ys),5);
 function X(v){return L+(v-xt[0])/((xt[xt.length-1]-xt[0])||1)*pw;}function Y(v){return T+ph-(v-yt[0])/((yt[yt.length-1]-yt[0])||1)*ph;}
 yt.forEach(function(v){var y=Y(v);el('line',{x1:L,x2:L+pw,y1:y,y2:y,'class':'rc-gl'},svg);el('text',{x:L-6,y:y+4,'text-anchor':'end'},svg).textContent=num(v);});
 xt.forEach(function(v){el('text',{x:X(v),y:H-6,'text-anchor':'middle'},svg).textContent=num(v);});
 var g=el('g',{},svg);pts.forEach(function(p){el('circle',{cx:X(p[0]),cy:Y(p[1]),r:2,fill:a.color,'fill-opacity':.6},g);});
 var tip=document.createElement('div');tip.className='rc-tip';tip.style.display='none';box.appendChild(tip);var ring=el('circle',{r:5,fill:'none',stroke:a.color,'stroke-width':2,visibility:'hidden'},svg),full=fullFmt(d.zone);
 svg.addEventListener('mousemove',function(ev){var r=svg.getBoundingClientRect(),px=ev.clientX-r.left,py=ev.clientY-r.top,best=null,bd=Infinity;pts.forEach(function(p){var dx=X(p[0])-px,dy=Y(p[1])-py,dd=dx*dx+dy*dy;if(dd<bd){bd=dd;best=p;}});if(!best||bd>900){ring.setAttribute('visibility','hidden');tip.style.display='none';return;}
  ring.setAttribute('cx',X(best[0]));ring.setAttribute('cy',Y(best[1]));ring.setAttribute('visibility','visible');tip.innerHTML='<b>'+esc(full.format(new Date(best[2])))+'</b><div><span>'+esc(a.label)+'</span><span>'+num(best[0])+'</span></div><div><span>'+esc(b.label)+'</span><span>'+num(best[1])+'</span></div>';tip.style.display='block';tip.style.left=Math.min(px+14,W-tip.offsetWidth)+'px';tip.style.top=Math.max(0,py-60)+'px';});
 svg.addEventListener('mouseleave',function(){ring.setAttribute('visibility','hidden');tip.style.display='none';});
}
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
var charts=[];
document.querySelectorAll('.rc-chart').forEach(function(box){var js=box.querySelector('script');var d;try{d=JSON.parse(js.textContent);}catch(e){return;}d._json=js;var off={},c={box:box,d:d,off:off};charts.push(c);
 var legend=box.parentNode.querySelector('.rc-legend');if(legend)legend.querySelectorAll('tbody tr').forEach(function(tr,i){var s=d.series[i];if(!s)return;tr.style.setProperty('--c',s.color);tr.title=words.hide||'';tr.addEventListener('click',function(){off[i]=!off[i];tr.classList.toggle('rc-off',!!off[i]);draw(box,d,off);});});
 draw(box,d,off);});
var timer;window.addEventListener('resize',function(){clearTimeout(timer);timer=setTimeout(function(){charts.forEach(function(c){draw(c.box,c.d,c.off);});},120);});
var links=[].slice.call(document.querySelectorAll('.rc-outline a'));
if(links.length&&'IntersectionObserver' in window){var heads=links.map(function(a){return document.getElementById(a.getAttribute('href').slice(1));});
 var io=new IntersectionObserver(function(){var top=null;heads.forEach(function(h,i){if(h&&h.getBoundingClientRect().top<120)top=i;});links.forEach(function(a,i){a.classList.toggle('rc-here',i===(top==null?0:top));});},{rootMargin:'0px 0px -60% 0px'});
 heads.forEach(function(h){if(h)io.observe(h);});}
})();
"""

__all__ = ["MEDIA_TYPE", "render"]
