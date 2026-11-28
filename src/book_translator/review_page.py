"""The interactive part of the review page: one card at a time, producing the choices file.

Plain, small and offline. The cards travel as JSON inside the page; the script builds every
element with `textContent`, so card text (which is book text) is never treated as markup.
"""

import json
from html import escape
from typing import Any

CSS = """
:root{--bg:#EEF2F3;--surface:#fff;--ink:#14232A;--muted:#5A7077;--line:#D5DEE1;--accent:#0E6B73;
--accent-soft:#DDF0F1;--accent-ink:#fff;--amber:#B26A00;--amber-soft:#FCEFD3}
@media (prefers-color-scheme:dark){:root{--bg:#0E181B;--surface:#152428;--ink:#E4EDEF;
--muted:#8CA3A9;--line:#27393E;--accent:#55C2CA;--accent-soft:#12383C;--accent-ink:#06191B;
--amber:#E8B04A;--amber-soft:#3A2D10;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif;
padding:16px 16px 88px}
.wrap{max-width:680px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
h1,h2,h3,p{margin:0}h1{font:500 24px/1.2 Georgia,serif}
.muted{color:var(--muted);font-size:14px}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
.chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(40px,1fr));gap:6px}
.chip{height:40px;border-radius:8px;border:1.5px solid var(--line);background:var(--surface);
color:var(--muted);font:500 13px ui-monospace,monospace;cursor:pointer;padding:0}
.chip[data-s=confirmed]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.chip[data-s=changed]{background:var(--amber-soft);border-color:var(--amber);color:var(--amber)}
.chip[aria-current=true]{outline:3px solid var(--ink);outline-offset:2px}
.card{background:var(--surface);border-radius:16px;padding:18px;display:flex;
flex-direction:column;gap:14px}
.context{margin:0;padding-left:12px;border-left:3px solid var(--line);font:18px/1.45 Georgia,serif;
overflow-wrap:anywhere}
.detail{font-size:14px;color:var(--muted);overflow-wrap:anywhere}
.opt{display:flex;gap:12px;align-items:flex-start;padding:14px;border:1.5px solid var(--line);
border-radius:12px;cursor:pointer;min-height:56px;background:var(--surface)}
.opt:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
.opt:has(input:focus-visible){outline:3px solid var(--accent);outline-offset:2px}
.opt input{width:22px;height:22px;margin:2px 0 0;flex:none;accent-color:var(--accent)}
.opt span{display:flex;flex-direction:column;gap:2px;min-width:0;overflow-wrap:anywhere}
.badge{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
color:var(--accent)}
.other{width:100%;min-height:72px;font:inherit;color:var(--ink);background:var(--surface);
border:1.5px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:6px}
.other:focus{outline:3px solid var(--accent);outline-offset:1px}
.pager{position:fixed;left:0;right:0;bottom:0;background:var(--surface);
border-top:1px solid var(--line);padding:10px 16px}
.pager div{max-width:680px;margin:0 auto;display:grid;grid-template-columns:1fr auto 1fr;
gap:12px;align-items:center}
.btn{font:600 16px system-ui,sans-serif;cursor:pointer;padding:12px 16px;border-radius:12px;
min-height:48px;border:1.5px solid var(--accent);background:var(--accent);color:var(--accent-ink)}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
.btn:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.btn[disabled]{opacity:.5;cursor:default}
.finish{background:var(--surface);border-radius:16px;padding:18px;display:flex;
flex-direction:column;gap:10px}
.finish textarea{width:100%;min-height:96px;font:13px ui-monospace,monospace;color:var(--ink);
background:var(--bg);border:1.5px solid var(--line);border-radius:10px;padding:8px}
details{background:var(--surface);border-radius:12px;padding:10px 14px}
li{overflow-wrap:anywhere}
"""

SCRIPT = r"""
(function(){
var data=JSON.parse(document.getElementById('review-data').textContent);
var cards=data.cards||[];
var app=document.getElementById('app');
document.getElementById('static').hidden=true;
if(!cards.length){app.hidden=true;document.getElementById('static').hidden=false;return;}
var picks={},idx=0;
cards.forEach(function(c){if(c.choice){picks[c.id]=c.choice;}});
function h(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;
if(text!=null)e.textContent=text;return e;}
function status(c){var p=picks[c.id];if(p==null)return'open';
return p===c.recommended?'confirmed':'changed';}
function current(c){return picks[c.id]!=null?picks[c.id]:c.recommended;}
function counts(){var n={open:0,confirmed:0,changed:0};
cards.forEach(function(c){n[status(c)]++;});return n;}
function result(){var out={};cards.forEach(function(c){
if(picks[c.id]!=null){out[c.id]=picks[c.id];}});return JSON.stringify(out,null,2);}
function chrome(){
var n=counts(),done=n.confirmed+n.changed;
document.getElementById('bar').style.width=(done/cards.length*100)+'%';
document.getElementById('stats').textContent=done+' of '+cards.length+' reviewed, '+n.changed+
' changed, '+n.open+' still open (they keep the recommendation)';
var chips=document.getElementById('chips');chips.textContent='';
cards.forEach(function(c,i){var b=h('button','chip',String(i+1));b.type='button';
b.setAttribute('data-s',status(c));b.setAttribute('aria-label',c.id+', '+status(c));
b.setAttribute('aria-current',i===idx?'true':'false');
b.addEventListener('click',function(){idx=i;card();});chips.appendChild(b);});
document.getElementById('pos').textContent=(idx+1)+' / '+cards.length;
document.getElementById('prev').disabled=idx===0;
document.getElementById('next').disabled=idx===cards.length-1;
document.getElementById('out').value=result();}
function card(){
var c=cards[idx],slot=document.getElementById('slot'),cur=current(c);slot.textContent='';
var box=h('article','card');box.setAttribute('aria-label',c.id);
box.appendChild(h('p','muted',c.id));
box.appendChild(h('h2',null,c.question));
if(c.context){box.appendChild(h('blockquote','context',c.context));}
var group=h('div');group.setAttribute('role','radiogroup');
group.style.cssText='display:flex;flex-direction:column;gap:10px';
var listed=false;
(c.options||[]).forEach(function(o){
var label=h('label','opt'),input=h('input');input.type='radio';input.name='choice';
input.checked=o===cur;listed=listed||o===cur;
input.addEventListener('change',function(){picks[c.id]=o;chrome();});
var text=h('span');
if(o===c.recommended){text.appendChild(h('span','badge','Recommended'));}
text.appendChild(h('span',null,o));label.appendChild(input);label.appendChild(text);
group.appendChild(label);});
var other=null;
if(c.free_text){
var label=h('label','opt'),input=h('input');input.type='radio';input.name='choice';
input.checked=!listed;var text=h('span');
text.appendChild(h('span',null,'Other (your own wording)'));
other=h('textarea','other');other.setAttribute('aria-label','Your own wording');
if(!listed){other.value=cur;}
other.addEventListener('input',function(){var v=other.value.trim();input.checked=true;
if(v){picks[c.id]=v;}else{delete picks[c.id];}chrome();});
input.addEventListener('change',function(){other.focus();});
text.appendChild(other);label.appendChild(input);label.appendChild(text);group.appendChild(label);}
box.appendChild(group);
if(c.why){box.appendChild(h('p','detail','Why: '+c.why));}
slot.appendChild(box);chrome();}
function go(d){idx=Math.max(0,Math.min(cards.length-1,idx+d));card();}
document.getElementById('prev').addEventListener('click',function(){go(-1);});
document.getElementById('next').addEventListener('click',function(){go(1);});
document.getElementById('copy').addEventListener('click',function(){
var out=document.getElementById('out'),msg=document.getElementById('msg');
function fallback(){out.focus();out.select();msg.textContent='Select and copy the text above.';}
if(navigator.clipboard&&navigator.clipboard.writeText){
navigator.clipboard.writeText(out.value).then(function(){msg.textContent='Copied.';},fallback);
}else{fallback();}});
document.getElementById('download').addEventListener('click',function(){
var a=document.createElement('a');
a.href=URL.createObjectURL(new Blob([result()],{type:'application/json'}));
a.download='choices.json';document.body.appendChild(a);a.click();a.remove();});
var auto=data.auto_resolved||[];
if(auto.length){var d=h('details'),s=h('summary',null,'Settled automatically ('+auto.length+')');
d.appendChild(s);var ul=h('ul');auto.forEach(function(a){
ul.appendChild(h('li',null,a.id+': '+a.span+' = '+a.resolution));});d.appendChild(ul);
document.getElementById('autoslot').appendChild(d);}
card();
})();
"""


def embed(document: dict[str, Any]) -> str:
    """The document as JSON safe to place inside a script element: no `<`, `>` or `&` survive."""
    text = json.dumps(document, ensure_ascii=False, default=str)
    for char, code in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        text = text.replace(char, code)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def interactive(title: str, document: dict[str, Any], static: str) -> str:
    """The whole page. `static` is the plain listing, shown when scripts are off.

    `title` is plain text; it is escaped here.
    """
    title = escape(title)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Review: {title}</title><style>{CSS}</style></head><body>"
        f'<div class="wrap"><h1>Review: {title}</h1>'
        '<div id="app"><div class="bar"><i id="bar"></i></div>'
        '<p class="muted" id="stats"></p><div class="chips" id="chips"></div>'
        '<div id="slot"></div><div id="autoslot"></div>'
        '<section class="finish"><h3>Your choices</h3>'
        '<p class="muted">Copy them or download the file, then run '
        "<code>book-translator approve &lt;workspace&gt; --choices choices.json</code>.</p>"
        '<textarea id="out" readonly aria-label="Choices as JSON"></textarea>'
        '<button class="btn" id="copy" type="button">Copy choices</button>'
        '<button class="btn ghost" id="download" type="button">Download choices.json</button>'
        '<p class="muted" id="msg" role="status"></p></section>'
        '<nav class="pager"><div><button class="btn ghost" id="prev" type="button">Back</button>'
        '<span class="muted" id="pos"></span>'
        '<button class="btn" id="next" type="button">Next</button></div></nav></div>'
        f'<div id="static">{static}</div></div>'
        f'<script type="application/json" id="review-data">{embed(document)}</script>'
        f"<script>{SCRIPT}</script></body></html>"
    )
