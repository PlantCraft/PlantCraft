// The home page: the four reasons (each with a small animation) and the suite's apps. No library.
(()=>{
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const CH=[{"q": "Why did the furnace outlet temperature alarm fire at 14:05?", "a": "TIC-201 rose 6 \u00b0C in 12 minutes. The fuel valve FV-201 stayed at 62 % while its controller asked for less: it looks stuck. Same pattern on Monday. First step: ask maintenance to stroke-test FV-201.", "pts": [40, 41, 40, 42, 41, 43, 47, 52, 55, 57, 56, 55]}, {"q": "What should we fix first this week?", "a": "Three issues cost the most: furnace efficiency is 3 % below last month, analyzer AT-210 has been frozen since Friday, and the valve on PIC-022 is sticking. I opened a draft action for each, ordered by impact.", "pts": [21, 14, 9, 6, 4, 3, 2, 2, 1, 1, 1, 1]}, {"q": "What changed in column C-100 since Monday?", "a": "The reflux ratio went from 2.4 to 2.9 on Tuesday at 09:10, after a setpoint change by the shift. Top purity improved 0.3 %, steam use rose 4 %. No alarms linked to it.", "pts": null}];
// apps
$$('.atab').forEach(b=>b.onclick=()=>$$('.atab,.apane').forEach(e=>e.classList.toggle('on',e.dataset.i===b.dataset.i)));
// pillar animations, each restartable
let run=0;
const ANIM={
secure:async(id)=>{const t=$$('#ticks li');t.forEach(x=>x.classList.remove('on'));for(const x of t){await sleep(700);if(id!==run)return;x.classList.add('on')}},
llm:async(id)=>{await chat(id)},
fast:async(id)=>{const T=$('#term'),P=$('#prog'),F=$('#finds'),K=$('#clock');T.innerHTML='';F.innerHTML='';P.style.width='0';
 const steps=[['$ ./install.sh --all-apps --demo',''],['checking the bundle signature… ok','g'],['loading 16 images…',''],['starting the platform and 8 apps…',''],['creating the admin account… ok','g'],['Ready: open https://plant-server/','g']];
 let sec=0;const clk=setInterval(()=>{sec+=37;K.textContent=String(Math.floor(sec/60)).padStart(2,'0')+':'+String(sec%60).padStart(2,'0')},120);
 for(let i=0;i<steps.length;i++){if(id!==run){clearInterval(clk);return}T.innerHTML+=(steps[i][1]?'<span class="g">'+steps[i][0]+'</span>':steps[i][0])+'\n';P.style.width=((i+1)/steps.length*100)+'%';await sleep(750)}
 clearInterval(clk);K.textContent='09:42';await sleep(400);
 for(const f of ['<b>2 signals</b> frozen since 03:00','<b>Steam per ton</b> 8 % above target','<b>Alarm flood</b> on unit 200 every morning']){if(id!==run)return;F.insertAdjacentHTML('beforeend','<li>'+f+'</li>');await sleep(700)}}};
let k=0,skip=false;
function chart(p){const w=280,h=80,mx=Math.max(...p),mn=Math.min(...p);const pts=p.map((v,i)=>`${(i/(p.length-1))*(w-20)+10},${h-10-(v-mn)/(mx-mn||1)*(h-20)}`).join(' ');return `<svg width="${w}" height="${h}"><polyline fill="none" stroke="#2e5a88" stroke-width="2" points="${pts}"/></svg>`}
async function chat(id){const M=$('#msgs');for(;;){if(id!==run)return;skip=false;const c=CH[k%CH.length];k++;M.innerHTML='';const q=document.createElement('div');q.className='mq';M.appendChild(q);
 for(const ch of c.q){if(id!==run||skip)break;q.textContent+=ch;await sleep(20)}q.textContent=c.q;await sleep(300);
 const a=document.createElement('div');a.className='ma';a.innerHTML='<span class="dots"><i></i><i></i><i></i></span>';M.appendChild(a);await sleep(skip?0:1100);a.textContent='';
 for(const w of c.a.split(' ')){if(id!==run)return;if(skip)break;a.textContent+=(a.textContent?' ':'')+w;await sleep(40)}a.textContent=c.a;if(c.pts)a.insertAdjacentHTML('beforeend',chart(c.pts));
 for(let i=0;i<60&&!skip;i++){if(id!==run)return;await sleep(100)}}}
$('#nextq').onclick=()=>{skip=true};

function showP(key){$$('.ptab,.ppane').forEach(e=>{e.classList.toggle('on',e.dataset.p===key);if(e.classList.contains('ptab'))e.setAttribute('aria-pressed',e.dataset.p===key)});run++;ANIM[key](run)}

// start the first pillar when it scrolls into view
new IntersectionObserver((es,o)=>{if(es[0].isIntersecting){const t=$('.ptab.on');if(t)showP(t.dataset.p);o.disconnect()}},{threshold:.3}).observe($('#pillars'));

// ---- Open pillar: blocks run one by one, the data under them shows what each block does
let ex=0,sel=0,view='data';
function rng(s){return()=>{s=(s*16807)%2147483647;return s/2147483647-.5}}
const N=96,R1=rng(7),R2=rng(11),R3=rng(23),R4=rng(5);
const ix=[...Array(N).keys()];
// example 1: feed flow, disturbance grows in the second half
const ff=ix.map(i=>50+i*.12+Math.sin(i/9)*1.2+R1()*(i<48?1.6:5));
const ffd=ff.map((v,i)=>v-(50+i*.12));
const std=ix.map(i=>{const a=ffd.slice(Math.max(0,i-8),i+1),m=a.reduce((s,x)=>s+x,0)/a.length;return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/a.length)});
// example 2: analyzer frozen from sample 60
const an=ix.map(i=>i<60?7.2+Math.sin(i/6)*.25+R2()*.3:7.31);
const dif=ix.map(i=>i?Math.abs(an[i]-an[i-1]):0);
// example 3: boiler, 30 days
const D=30,prod=[...Array(D).keys()].map(i=>100+R3()*24+(i%7>4?-18:0)),steam=prod.map((p,i)=>p*(i<15?1.0:1.08)*2.1+R3()*4);
const ratio=steam.map((s,i)=>s/prod[i]);
const vib=ix.map(i=>2.1+Math.sin(i/5)*.25+R4()*.9),vibd=ix.map(i=>{const a=vib.slice(Math.max(0,i-12),i+1);return a.reduce((x,y)=>x+y,0)/a.length});
// example 4: valve, smooth controller output, position moves in jumps
const op=ix.map(i=>40+Math.sin(i/12)*8);let pos=[],p=op[0];op.forEach(v=>{if(Math.abs(v-p)>2.2)p=v;pos.push(p)});
const jumps=ix.filter(i=>i&&pos[i]!==pos[i-1]);
const BLUE='#2e5a88',GREY='#aeb4bd',RED='#c0392b',AMB='#c77c02',GRN='#1e8449';
const HC={[RED]:'#fdecea',[AMB]:'#fdf2e0',[GRN]:'#e6f4ea'};
const EX=[
{asset:'Feed line',goal:'Detect disturbances on the feed line',tag:'Process',res:'High disturbance: variability 3× the baseline',
 py:['<span class="c"># open Python behind these blocks</span>','<span class="k">def</span> disturbance(flow, baseline):','    x = detrend(flow)             <span class="c"># Remove trend</span>','    v = rolling_std(x, "1h")      <span class="c"># Variability</span>','    ratio = v[-24:].mean() / baseline','    <span class="k">return</span> ratio  <span class="c"># 3.1 → high</span>'],
 steps:[
 {b:'Feed flow',l:1,t:'The raw signal from the historian: last 4 days of feed flow.',s:[{d:ff,c:BLUE}]},
 {b:'Remove trend',l:2,t:'The slow rise is taken out. Only the fast changes are left.',s:[{d:ff,c:GREY,w:1},{d:ffd.map(v=>v+50),c:BLUE}]},
 {b:'Variability',l:3,t:'How much it moves in each hour. It grows in the last two days.',s:[{d:std,c:BLUE,fill:1}]},
 {b:'Compare with baseline',l:4,t:'Recent variability against the normal level for this signal.',s:[{d:std,c:BLUE},{d:ix.map(()=>1),c:RED,dash:1,lab:'baseline'}],hi:[72,95]},
 {b:'Result',l:5,t:'3.1 times the baseline: flagged as a high disturbance for the feed line.',bars:[['Baseline',1,GREY],['Last day',3.1,RED]]}]},
{asset:'Analyzer AT-210',goal:'Detect a frozen analyzer signal (AT-210)',tag:'Data quality',res:'Frozen signal since 03:00',
 py:['<span class="c"># open Python behind these blocks</span>','<span class="k">def</span> frozen(x, noise, hours=6):','    change = rolling_change(x, "10min")','    flat = change &lt; noise           <span class="c"># Below noise level</span>','    run = longest_run(flat)','    <span class="k">return</span> run &gt;= hours   <span class="c"># 9 h → frozen</span>'],
 steps:[
 {b:'Signal',l:1,t:'The analyzer value. It looks normal at first sight.',s:[{d:an,c:BLUE}]},
 {b:'Rolling change',l:2,t:'How much the value changes from one sample to the next.',s:[{d:dif,c:BLUE,fill:1}]},
 {b:'Below noise level',l:3,t:'A real analyzer always moves a little. Here it stops moving at all.',s:[{d:dif,c:BLUE},{d:ix.map(()=>.04),c:RED,dash:1,lab:'noise level'}],hi:[60,95]},
 {b:'For 6 hours',l:4,t:'It has stayed flat for 9 hours, longer than the 6-hour limit.',s:[{d:an,c:BLUE}],hi:[60,95],hl:'9 h flat'},
 {b:'Result',l:5,t:'Frozen since 03:00. Check the analyzer before trusting its value.',bars:[['Limit',6,GREY],['Flat for',9,RED]],u:' h'}]},
{asset:'Boiler B-1',goal:'Track steam use per ton on boiler B-1',tag:'Energy',st:'warn',res:'Uses 8 % more steam per ton than its target',
 py:['<span class="c"># open Python behind these blocks</span>','<span class="k">def</span> specific_use(steam, prod):','    s, p = daily(steam), daily(prod)','    r = s / p                      <span class="c"># Ratio</span>','    gap = r[-15:].mean() / TARGET - 1','    <span class="k">return</span> gap  <span class="c"># +8 % (lower is better)</span>'],
 steps:[
 {b:'Steam flow',l:2,t:'Tons of steam used each day, last 30 days.',s:[{d:steam,c:BLUE,bar:1}]},
 {b:'Production',l:2,t:'Tons produced each day. Weekends are lower.',s:[{d:prod,c:GREY,bar:1}]},
 {b:'Ratio',l:3,t:'Steam per ton of product. It does not depend on how much was produced. Lower is better.',s:[{d:ratio,c:BLUE}],yl:'t steam / t product'},
 {b:'Compare with target',l:4,t:'Up to day 15 it was on target. Since then it uses more steam for each ton.',s:[{d:ratio,c:BLUE},{d:ratio.map(()=>2.1),c:GRN,dash:1,lab:'target 2.10'}],hi:[15,29],hc:AMB,hl:'+8 % above target',yl:'t steam / t product'},
 {b:'Result',l:5,t:'8 % more steam per ton than the target. Not urgent, but worth a look at the boiler.',bars:[['Target',2.1,GRN],['Last 15 days',2.27,AMB]],u:' t/t'}]},
{asset:'Pump P-101',goal:'Watch the vibration of pump P-101',tag:'Equipment',st:'ok',res:'Healthy: vibration within its normal range',
 py:['<span class="c"># open Python behind these blocks</span>','<span class="k">def</span> vibration_ok(v, band):','    d = daily_mean(v)              <span class="c"># Daily average</span>','    inside = band.low &lt;= d &lt;= band.high','    <span class="k">return</span> inside.all()  <span class="c"># True → OK</span>'],
 steps:[
 {b:'Vibration',l:1,t:'Pump vibration from the historian, last 30 days.',s:[{d:vib,c:BLUE,w:1}],yl:'mm/s'},
 {b:'Daily average',l:2,t:'The average of each day, so short peaks do not count.',s:[{d:vib,c:GREY,w:1},{d:vibd,c:BLUE}],yl:'mm/s'},
 {b:'Normal range',l:3,t:'The range this pump had over the last year. Every day stays inside it.',s:[{d:vibd,c:BLUE},{d:vib.map(()=>3.2),c:GRN,dash:1,lab:'normal range'},{d:vib.map(()=>1.2),c:GRN,dash:1}],yl:'mm/s'},
 {b:'Result',l:4,t:'Nothing to do. Analytics keeps checking it every day.',bars:[['Upper limit',3.2,GREY],['Last 30 days',2.1,GRN]],u:' mm/s'}]},
{asset:'Valve FV-104',goal:'Detect a sticking control valve (FV-104)',tag:'Equipment',res:'Valve sticking: moves in jumps',
 py:['<span class="c"># open Python behind these blocks</span>','<span class="k">def</span> stiction(op, pos):','    steps = step_changes(pos)      <span class="c"># jumps</span>','    lag = lag_between(op, steps)','    <span class="k">return</span> len(steps), lag  <span class="c"># '+jumps.length+' jumps</span>'],
 steps:[
 {b:'Controller output',l:1,t:'What the controller asks the valve to do: a smooth curve.',s:[{d:op,c:GREY}]},
 {b:'Valve position',l:2,t:'What the valve actually does: it holds, then jumps.',s:[{d:op,c:GREY,w:1},{d:pos,c:BLUE,step:1}]},
 {b:'Stick-slip pattern',l:3,t:'Each red mark is a jump after the valve was stuck.',s:[{d:op,c:GREY,w:1},{d:pos,c:BLUE,step:1}],marks:jumps},
 {b:'Result',l:4,t:jumps.length+' jumps in 4 days: the valve is sticking. Plan maintenance.',bars:[['Healthy valve',0,GREY],['FV-104',jumps.length,RED]],u:' jumps'}]}];
function plot(st){const W=520,H=150,P=8;
 if(st.bars){const mx=Math.max(...st.bars.map(b=>b[1]))*1.15||1;return `<svg viewBox="0 0 ${W} ${H}" class="plt">`+st.bars.map((b,i)=>{const y=22+i*58,w=(W-170)*b[1]/mx;return `<text x="0" y="${y+22}" class="ax">${b[0]}</text><rect x="110" y="${y}" height="34" rx="6" width="${Math.max(w,2)}" fill="${b[2]}" class="gx"/><text x="${118+w}" y="${y+23}" class="bv" fill="${b[2]}">${b[1]}${st.u||'×'}</text>`}).join('')+'</svg>'}
 const all=st.s.flatMap(s=>s.d),mx=Math.max(...all),mn=Math.min(...all,st.s.some(s=>s.bar||s.fill)?0:Infinity),rg=(mx-mn)||1;
 const X=(i,n)=>P+i/(n-1)*(W-2*P),Y=v=>H-P-(v-mn)/rg*(H-2*P-14);
 let g='';
 if(st.hi){const n=st.s[0].d.length;g+=`<rect x="${X(st.hi[0],n)}" y="0" width="${X(st.hi[1],n)-X(st.hi[0],n)}" height="${H}" fill="${HC[st.hc||RED]}"/>`;if(st.hl)g+=`<text x="${X(st.hi[0],n)+6}" y="14" class="ax" fill="${st.hc||RED}">${st.hl}</text>`}
 if(st.yl)g+=`<text x="${P}" y="12" class="ax">${st.yl}</text>`;
 st.s.forEach(s=>{const n=s.d.length;
  if(s.bar){const bw=(W-2*P)/n*.7;s.d.forEach((v,i)=>g+=`<rect x="${X(i,n)-bw/2}" y="${Y(v)}" width="${bw}" height="${H-P-Y(v)}" rx="2" fill="${s.c}" class="gr"/>`);return}
  let pts=s.d.map((v,i)=>[X(i,n),Y(v)]);if(s.step)pts=pts.flatMap((p,i)=>i?[[p[0],pts[i-1][1]],p]:[p]);
  const d=pts.map(p=>p.map(x=>x.toFixed(1)).join(',')).join(' ');
  if(s.fill)g+=`<polygon points="${P},${H-P} ${d} ${W-P},${H-P}" fill="${s.c}" opacity=".12"/>`;
  g+=`<polyline points="${d}" fill="none" stroke="${s.c}" stroke-width="${s.w||2}" ${s.dash?'stroke-dasharray="6 5"':'pathLength="1" class="draw"'}/>`;
  if(s.lab)g+=`<text x="${W-P-4}" y="${Y(s.d[0])-6}" text-anchor="end" class="ax" fill="${s.c}">${s.lab}</text>`});
 if(st.marks)st.marks.forEach(i=>g+=`<circle cx="${X(i,N)}" cy="${Y(pos[i])}" r="4.5" fill="${RED}" class="gr"/>`);
 return `<svg viewBox="0 0 ${W} ${H}" class="plt">${g}</svg>`}
function showStep(i){const e=EX[ex%EX.length],st=e.steps[i];sel=i;
 $$('#chain .blk').forEach((b,j)=>{b.classList.toggle('lit',j<=i||b.dataset.done==='1');b.classList.toggle('sel',j===i)});
 $('#dstep').innerHTML=`<b>${i+1}. ${st.b}</b>`;$('#dtext').textContent=st.t;
 $('#dplot').innerHTML=plot(st);
 $('#py').innerHTML=e.py.map((l,j)=>`<span class="ln${j===st.l?' on':''}">${l}</span>`).join('\n')}
ANIM.open=async(id)=>{const e=EX[ex%EX.length];$('#exgoal').textContent=e.goal;$('#extag').textContent=e.tag;$('#exdot').className='rdot '+(e.st||'alarm');$('#exres').textContent=e.res;
 $('#chain').innerHTML=e.steps.map((s,i)=>`<button class="blk" data-i="${i}">${s.b}</button>`).join('<span class="arr">→</span>');
 $$('#chain .blk').forEach(b=>b.onclick=()=>{run++;$$('#chain .blk').forEach(x=>x.dataset.done='1');showStep(+b.dataset.i);$('#dhint').textContent='Click any block to see its data'});
 $('#dhint').textContent='Running the blocks…';
 for(let i=0;i<e.steps.length;i++){if(id!==run)return;showStep(i);await sleep(2200)}
 if(id!==run)return;$$('#chain .blk').forEach(x=>x.dataset.done='1');$('#dhint').textContent='Click any block to see its data'};
$('#nextex').onclick=()=>{ex++;run++;ANIM.open(run)};
$$('.dseg button').forEach(b=>b.onclick=()=>{view=b.dataset.v;$$('.dseg button').forEach(x=>x.classList.toggle('on',x===b));$('#dview').dataset.v=view});

// phone: the four reasons one under the other (each starts when it comes into view); the apps a
// list whose open item shows right under it
const MQ=matchMedia('(max-width:760px)');
function phoneLayout(){const m=MQ.matches;document.body.classList.toggle('stack',m);
 $$('.ptab').forEach(t=>{const p=$(`.ppane[data-p="${t.dataset.p}"]`);if(m)t.after(p);else $('.pbox').appendChild(p)});
 $$('.atab').forEach(t=>{const p=$(`.apane[data-i="${t.dataset.i}"]`);if(m)t.after(p);else $('.apanes').appendChild(p)})}
function toTop(el){scrollTo({top:el.getBoundingClientRect().top+scrollY-64,behavior:'smooth'})}
$$('.ptab').forEach(b=>b.addEventListener('click',()=>{if(!MQ.matches)showP(b.dataset.p)}));
$$('.atab').forEach(b=>b.onclick=()=>{const was=b.classList.contains('on');$$('.atab,.apane').forEach(e=>e.classList.toggle('on',e.dataset.i===b.dataset.i&&!(MQ.matches&&was)));if(MQ.matches&&!was)setTimeout(()=>toTop(b),30)});
const seen=new IntersectionObserver(es=>{if(!MQ.matches)return;es.forEach(e=>{if(e.isIntersecting){run++;ANIM[e.target.dataset.p](run)}})},{threshold:.15});
$$('.ppane').forEach(p=>seen.observe(p));
MQ.addEventListener('change',phoneLayout);phoneLayout();
$$('.zoom').forEach(i=>i.addEventListener('click',()=>{$('#lbimg').src=i.src;$('#lb').classList.add('on')}));$('#lb').addEventListener('click',()=>$('#lb').classList.remove('on'));
})();
