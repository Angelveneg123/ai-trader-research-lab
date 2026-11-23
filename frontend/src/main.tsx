import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity,ShieldCheck,Wallet,BrainCircuit,BarChart3,Clock3,LayoutDashboard,History,ChartCandlestick,Newspaper,Settings,FlaskConical,FileText,PlugZap,AlertTriangle,RefreshCw,Server,LockKeyhole,Coins,TrendingUp,TrendingDown} from 'lucide-react';
import './style.css';
import {EntryControls} from './EntryControls';
import {MarketOverview, type MarketSummary} from './MarketOverview';
import {DemoPanel, NewsPanel, ProspectivePanel, ReportsPanel, type Prospective} from './ProspectivePanel';
type Budget={limit:number;spent:number|null;reserved?:number;remaining?:number};
type AIResearch={gemini:{configured:boolean;last_success:string|null;availability:string;model:string|null};openai:{configured:boolean;last_success:string|null;availability:string};journal_available:boolean;total_decisions:number;latest:({symbol:string;decision:string;confidence:number;reason:string;decision_time_utc:string;model:string;outcome?:string})|null;budget:{limit_usd:number;spent_usd:number|null;source:string}};
type Candle={time:number;open:number;high:number;low:number;close:number;volume:number};
type Quote={spread_points:number;stale:boolean};
type CandleResponse={quote?:Quote|null;symbol:string;timeframe:string;count:number;source:string;candles:Candle[];fetched_at:string};
const API_BASE=(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/,'');
async function apiGet<T>(path:string, signal?:AbortSignal):Promise<T>{
 const response=await fetch(`${API_BASE}${path}`,{signal});
 if(!response.ok){let detail='';try{const body=await response.json();detail=typeof body.detail==='string'?body.detail:(body.detail?.message??'');}catch{}throw new Error(`HTTP ${response.status}${detail?': '+detail:''}`)}
 const contentType=response.headers.get('content-type')||'';
 if(!contentType.includes('application/json'))throw new Error('El servidor no devolvió JSON. Verifica la URL del backend.');
 return response.json() as Promise<T>;
}
function CandleChart({candles,symbol}:{candles:Candle[];symbol:string}){
 const [hover,setHover]=useState<number|null>(null);
 const W=960,H=400,left=14,right=80,top=22,bottom=37;
 const low=Math.min(...candles.map(c=>c.low)),high=Math.max(...candles.map(c=>c.high));
 const padding=Math.max((high-low)*0.09,high*0.000005),min=low-padding,max=high+padding;
 const plotW=W-left-right,plotH=H-top-bottom;
 const y=(price:number)=>top+(max-price)/(max-min)*plotH;
 const step=plotW/candles.length,barWidth=Math.max(2,Math.min(13,step*.62));
 const digits=symbol.startsWith('XAUUSD')?2:symbol.startsWith('USDJPY')?3:5;
 const hovered=hover===null?null:candles[hover];
 return <div className="liveChart"><svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`Gráfico de velas ${symbol}`} onMouseLeave={()=>setHover(null)}>
 {Array.from({length:6},(_,i)=>{const price=min+(max-min)*i/5;const yy=y(price);return <g key={i}><line x1={left} x2={W-right} y1={yy} y2={yy} stroke="#294562" strokeDasharray="4 5" opacity=".65"/><text x={W-right+9} y={yy+4} fill="#8faaca" fontSize="12">{price.toFixed(digits)}</text></g>})}
 {candles.map((c,i)=>{const x=left+(i+.5)*step;const rising=c.close>=c.open;const color=rising?'#20d7a1':'#ff657d';const bodyTop=y(Math.max(c.open,c.close));const bodyBottom=y(Math.min(c.open,c.close));return <g key={c.time}><line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} stroke={color} strokeWidth="1.5"/><rect x={x-barWidth/2} y={bodyTop} width={barWidth} height={Math.max(1.5,bodyBottom-bodyTop)} fill={color}/><rect x={x-step/2} y={top} width={step} height={plotH} fill="transparent" onMouseEnter={()=>setHover(i)}/></g>})}
 {Array.from({length:6},(_,i)=>{const index=Math.min(candles.length-1,Math.floor(i*(candles.length-1)/5));const c=candles[index];return <text key={i} x={left+(index+.5)*step} y={H-12} textAnchor="middle" fontSize="12" fill="#8faaca">{new Date(c.time*1000).toLocaleString('es-NI',{timeZone:'America/Managua',hour:'2-digit',minute:'2-digit',hour12:false})}</text>})}
 {hover!==null&&<line x1={left+(hover+.5)*step} x2={left+(hover+.5)*step} y1={top} y2={H-bottom} stroke="#8adfff" strokeDasharray="3 4" opacity=".65"/>}
 </svg>{hovered&&<div className="candleTooltip">{new Date(hovered.time*1000).toLocaleString('es-NI',{timeZone:'America/Managua'})} · O {hovered.open.toFixed(digits)} · H {hovered.high.toFixed(digits)} · L {hovered.low.toFixed(digits)} · C {hovered.close.toFixed(digits)} · Vol {hovered.volume}</div>}</div>
}

type Audit={id:number;symbol:string;candle_time:number;decision:string;reason:string;context:{temporal_validation:string;h1:{trend:string;atr14:number|null;ema200:number|null};m15:{structure:string;bos_strength_atr:number|null};m5:{atr14:number|null}};outcomes:{horizon:number;gross_return:number;net_return_estimate:number|null}[]};
type Observation={id:number;symbol:string;candle_time:number;observed_at:string;decision:string;reason:string;context:{h1:{trend:string};m15:{structure:string};m5:{direction:string;body_ratio:number};data_counts:{h1:number;m15:number;m5:number}}};
type ResearchStatus={running:boolean;last_poll:string|null;last_error:string|null;total_observations:number;total_audits:number;orders_enabled:boolean};
type Dashboard={as_of:string;initial_balance:number;current_balance:number|null;equity:number|null;realized_pnl:number|null;floating_pnl:number|null;daily_drawdown_usd:number|null;open_positions:unknown[]|null;entries_blocked:boolean|null;mt5_error:string|null;mt5_error_code:string|null;mt5_native_code:number|null;mt5_connected:boolean;runtime:{mode:string;provider:string;checked_utc:string}|null;trades:unknown[];decisions:unknown[];session_allows_entries:boolean;execution_mode:string;api_budgets:Record<string,Budget>;symbols:string[];data_source:string;ai_research?:AIResearch};
type Page='Dashboard'|'Operaciones'|'IA y modelos'|'Mercados'|'Noticias'|'Investigación'|'Reportes'|'Configuración';
const nav:[Page,React.ReactNode][]=[['Dashboard',<LayoutDashboard/>],['Operaciones',<History/>],['IA y modelos',<BrainCircuit/>],['Mercados',<ChartCandlestick/>],['Noticias',<Newspaper/>],['Investigación',<FlaskConical/>],['Reportes',<FileText/>],['Configuración',<Settings/>]];
const cash=(v:number,decimals=2)=>'$'+Number(v).toFixed(decimals);
const amount=(v:number|null|undefined)=>v==null?'No disponible':cash(v);
const fallbackBudgets:Record<string,Budget>={openai:{limit:2.5,spent:null},gemini:{limit:2.5,spent:null}};

type ProtocolStatus={manifest_ready:boolean;manifest_hash:string|null;target_new:number;completed_new:number;pending_new:number;historical_decisions_total:number;running:boolean;attempted:number;last_error:string|null;last_message:string;budget_verified_usd:null;orders_sent:boolean};
function GeminiProtocolPanel(){
 const [state,setState]=useState<ProtocolStatus|null>(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false),[confirm,setConfirm]=useState(false);
 const [calls,setCalls]=useState(10),[ceiling,setCeiling]=useState(0.10),[token,setToken]=useState('');
 const refresh=async()=>{try{const r=await apiGet<ProtocolStatus>('/api/gemini/protocol');setState(r);setErr('')}catch(e){setErr(String(e))}};
 useEffect(()=>{refresh();const id=setInterval(refresh,3000);return()=>clearInterval(id)},[]);
 const send=async(path:string,payload?:object)=>{setBusy(true);try{const r=await fetch(`${API_BASE}${path}`,{method:'POST',headers:{'Content-Type':'application/json',...(token?{'Authorization':'Bearer '+token}:{})},body:JSON.stringify(payload??{})});if(!r.ok)throw new Error(await r.text());setState(await r.json());setErr('');setConfirm(false)}catch(e){setErr(String(e))}finally{setBusy(false)}};
 return <section className="panel section" style={{marginTop:16}}><div className="sectionTitle"><FlaskConical/> Gemini V1.9.6 · Protocolo congelado</div>
 <p className="muted small">Investigación EURUSD histórica · una fecha por día · reglas fijas · cero órdenes MT5. Las consultas pueden consumir cuota; el costo real NO está medido.</p>
 <div className="statusRow"><span>Decisiones registradas en SQLite</span><b>{state?.historical_decisions_total??'—'} / 100</b></div>
 <div className="statusRow"><span>Nuevas decisiones del manifiesto</span><b>{state?.completed_new??0} / 89</b></div>
 <div className="statusRow"><span>Manifiesto</span><b>{state?.manifest_ready?'CONGELADO':'SIN CREAR'}</b></div>
 {state?.manifest_hash&&<p className="muted small" style={{overflowWrap:'anywhere'}}>SHA256: {state.manifest_hash}</p>}
 <div className="statusRow"><span>Proceso</span><b>{state?.running?'EJECUTANDO':'DETENIDO'}</b></div>
 <p className="muted small">{state?.last_message??'Cargando...'}</p>
 {state?.last_error&&<p className="amberText">{state.last_error}</p>}{err&&<p className="amberText">{err}</p>}
 {!state?.manifest_ready?<button className="navItem" disabled={busy} onClick={()=>send('/api/gemini/protocol/prepare')}>Preparar y congelar 89 escenarios (sin API)</button>:<>
 <div className="statusRow"><label>Consultas máximas por lote (1–10)</label><input style={{width:70}} type="number" min={1} max={10} value={calls} onChange={e=>setCalls(Number(e.target.value))}/></div>
 <div className="statusRow"><label>Cota hipotética USD/consulta</label><input style={{width:90}} type="number" min="0.01" max="2.5" step="0.01" value={ceiling} onChange={e=>setCeiling(Number(e.target.value))}/></div>
 <p className="muted small">Reserva estimada del lote: ${(calls*ceiling).toFixed(2)} USD. No es un límite real de facturación; revisá la cuota en Google AI Studio.</p>
 <label className="muted small">Token de control <input type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/></label><br/><label className="muted small"><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)}/> Confirmo que deseo realizar consultas de pago o cuota a Gemini.</label>
 <button className="navItem" disabled={busy||!!state?.running||!confirm||!token||calls<1||calls>10||ceiling<=0||calls*ceiling>2.5} onClick={()=>send('/api/gemini/protocol/run',{confirm:true,max_calls:calls,usd_per_call_ceiling:ceiling,max_estimated_usd:Number((calls*ceiling).toFixed(4))})}>Iniciar lote controlado</button>
 </>}
 <p className="muted small">No se enviarán órdenes. Si se reinicia FastAPI durante un lote, consultá el estado antes de reanudar. Presupuesto real: sin datos verificados.</p>
 </section>
}
const DEFAULT_MARKETS = [
 {symbol:'EURUSDmicro',label:'EUR/USD'},
 {symbol:'USDJPYmicro',label:'USD/JPY'},
 {symbol:'XAUUSDmicro',label:'XAU/USD'},
];

function Mt5ConnectionNotice({data, symbol, refresh}: {data: Dashboard; symbol: string; refresh: () => void}) {
 const code=data.mt5_error_code;
 const title=code==='AUTHORIZATION_FAILED'?'MT5 requiere iniciar sesión'
   :code==='TERMINAL_BUSY'?'MT5 está atendiendo otra lectura':'Deriv MT5 sin conexión';
 const help=code==='TERMINAL_BUSY'?'El panel vuelve a comprobar la conexión automáticamente.'
   :'Abrí el terminal de Deriv con tu cuenta demo y verificá que el backend use ese mismo ejecutable.';
 return <section className="connectionNotice" aria-label="Conexión de Deriv MT5">
   <AlertTriangle size={20}/>
   <div>
     <strong>{title}</strong>
     <p>{help}</p>
     <details>
       <summary>Diagnóstico de conexión{data.mt5_native_code!=null?' · Código '+data.mt5_native_code:''}</summary>
       <p>{data.mt5_error??'Estado de MT5 no disponible.'}</p>
       {code!=='TERMINAL_BUSY'&&<p>Desde backend ejecutá <code>{'.\\.venv\\Scripts\\python.exe .\\diagnosticar_mt5.py --symbol '+symbol}</code></p>}
     </details>
   </div>
   <button type="button" className="connectionRetry" onClick={refresh}>Actualizar estado</button>
 </section>;
}

function App(){
const [marketOverview,setMarketOverview]=useState<MarketSummary[]|null>(null);
const [marketOverviewError,setMarketOverviewError]=useState('');
const [quote,setQuote]=useState<Quote|null>(null);const [prospective,setProspective]=useState<Prospective|null>(null),[prospectiveError,setProspectiveError]=useState('');const [audits,setAudits]=useState<Audit[]>([]),[observations,setObservations]=useState<Observation[]>([]),[researchStatus,setResearchStatus]=useState<ResearchStatus|null>(null),[researchError,setResearchError]=useState(''),[candles,setCandles]=useState<Candle[]>([]),[marketError,setMarketError]=useState(''),[marketLoading,setMarketLoading]=useState(false),[marketUpdated,setMarketUpdated]=useState(''),[data,setData]=useState<Dashboard|null>(null),[error,setError]=useState(''),[page,setPage]=useState<Page>('Dashboard'),[symbol,setSymbol]=useState('EURUSDmicro'),[tf,setTf]=useState('M5'),[updated,setUpdated]=useState('');
useEffect(()=>{
 if(page!=='Dashboard')return;
 const controller=new AbortController();
 let loading=false;
 const refresh=async()=>{
   if(loading)return;
   loading=true;
   try{
     const summary=await apiGet<{markets:MarketSummary[]}>('/api/prospective/markets',controller.signal);
     if(!controller.signal.aborted){setMarketOverview(summary.markets);setMarketOverviewError('');}
   }catch(e){
     if(!controller.signal.aborted)setMarketOverviewError(e instanceof Error?e.message:'Error al consultar los ciclos');
   }finally{loading=false;}
 };
 refresh();
 const timer=setInterval(refresh,5000);
 return()=>{controller.abort();clearInterval(timer);};
},[page]);
const [connectionRefresh,setConnectionRefresh]=useState(0);
const brokerConnected=data?.mt5_connected;
useEffect(()=>{
 const controller=new AbortController();
 let loading=false;
 const refresh=async()=>{
   if(loading)return;
   loading=true;
   try{
     const dashboard=await apiGet<Dashboard>('/api/dashboard',controller.signal);
     if(!controller.signal.aborted){
       setData(dashboard);setError('');
       setUpdated(new Date(dashboard.as_of).toLocaleTimeString('es-NI',{timeZone:'America/Managua'}));
     }
   }catch(e){
     if(!controller.signal.aborted)setError(e instanceof Error?e.message:'Error de conexión');
   }finally{loading=false;}
 };
 refresh();
 const timer=setInterval(refresh,5000);
 return()=>{controller.abort();clearInterval(timer);};
},[connectionRefresh]);
useEffect(()=>{
 setCandles([]);setQuote(null);setMarketUpdated('');setMarketError('');setMarketLoading(false);
 if(page!=='Dashboard'||!brokerConnected)return;
 const controller=new AbortController();
 let loading=false;
 const refresh=async()=>{
   if(loading)return;
   loading=true;setMarketLoading(true);
   try{
     const params=new URLSearchParams({symbol,timeframe:tf,limit:'120',include_quote:'true'});
     const result=await apiGet<CandleResponse>('/api/market/candles?'+params,controller.signal);
     if(!controller.signal.aborted){
       setCandles(result.candles);setQuote(result.quote??null);setMarketError('');
       setMarketUpdated(new Date(result.fetched_at).toLocaleTimeString('es-NI',{timeZone:'America/Managua'}));
     }
   }catch(e){
     if(!controller.signal.aborted){
       setCandles([]);setQuote(null);setMarketUpdated('');
       setMarketError(e instanceof Error?e.message:'Error de datos MT5');
     }
   }finally{
     loading=false;
     if(!controller.signal.aborted)setMarketLoading(false);
   }
 };
 refresh();
 const timer=setInterval(refresh,15000);
 return()=>{controller.abort();clearInterval(timer);};
},[page,symbol,tf,brokerConnected]);
useEffect(()=>{
 let active=true;
 const controller=new AbortController();
 setProspective(null);
 setProspectiveError('');
 const load=async()=>{try{
   const r=await apiGet<Prospective>('/api/prospective?symbol='+encodeURIComponent(symbol),controller.signal);
   if(active){setProspective(r);setProspectiveError('');}
 }catch(e){if(active)setProspectiveError(String(e));}};
 load();
 const timer=setInterval(load,5000);
 return()=>{active=false;controller.abort();clearInterval(timer);};
},[symbol]);
useEffect(()=>{let active=true;const load=async()=>{try{const r=await apiGet<{audits:Audit[]}>(`/api/research/audit?symbol=${encodeURIComponent(symbol)}&limit=8`);if(active)setAudits(r.audits)}catch{if(active)setAudits([])}};load();const timer=setInterval(load,15000);return()=>{active=false;clearInterval(timer)}},[symbol]);
useEffect(()=>{let mounted=true;const load=async()=>{try{const [r,status]=await Promise.all([apiGet<{observations:Observation[]}>(`/api/research/observations?symbol=${encodeURIComponent(symbol)}&limit=12`),apiGet<ResearchStatus>('/api/research/status')]);if(mounted){setObservations(r.observations);setResearchStatus(status);setResearchError('')}}catch(e){if(mounted){setResearchError(e instanceof Error?e.message:'Investigación no disponible')}}};load();const id=setInterval(load,15000);return()=>{mounted=false;clearInterval(id)}},[symbol]);
const ai=data?.ai_research;
const connected=!!data&&!error;
const budgets=prospective?.budget??data?.api_budgets??fallbackBudgets;
const initial=data?.initial_balance??100;
const balance=data?.current_balance;
const pnl=data?.realized_pnl;
const symbols=marketOverview??DEFAULT_MARKETS;
const geminiResponded=Boolean(prospective?.recent.some(row=>row.provider==='gemini'&&row.request_status==='saved'));
const operationalStatus=[
 {label:'Gemini',value:geminiResponded?'Decisión guardada para este mercado':prospective?.configured.gemini?'Clave configurada':'Sin configurar',ok:geminiResponded},
 {label:'OpenAI',value:!prospective?.openai_enabled?'Desactivado':prospective?.configured.openai?'Clave configurada':'Sin configurar',ok:false},
 {label:'Telegram',value:prospective?.reports[0]?.telegram_status==='sent'?'Último reporte enviado':'Sin envío registrado',ok:prospective?.reports[0]?.telegram_status==='sent'},
];
const showMarket=(next:string)=>{
 setSymbol(next);
 setPage('Dashboard');
 requestAnimationFrame(()=>document.getElementById('grafico-mercado')?.scrollIntoView?.({block:'start',behavior:'smooth'}));
};
useEffect(()=>{
 if(marketOverview?.length&&!marketOverview.some(m=>m.symbol===symbol))setSymbol(marketOverview[0].symbol);
},[marketOverview,symbol]);
const stat=(label:string,value:string,ico:React.ReactNode,cls='')=><div className={'stat panel '+cls}><div className="statIcon">{ico}</div><div><div className="muted">{label}</div><div className="statValue">{value}</div></div></div>;
const empty=(label:string)=><div className="empty"><LockKeyhole size={26}/><strong>{label}</strong></div>;
return <div className="app"><aside className="sidebar"><div className="brand"><div className="brandLogo">♉</div><div><b>AI Trader</b><small>Research Lab · V2.5</small></div></div><div className="navTitle">PLATAFORMA</div><nav>{nav.map(([name,ico])=><button key={name} className={'navItem '+(page===name?'selected':'')} onClick={()=>setPage(name)}>{ico}<span>{name}</span></button>)}</nav><div className="sidebarBottom"><span className="tinyDot"/> INVESTIGACIÓN DEMO <small>Motor MT5 separado</small></div></aside><div className="content"><header className="top"><div className="heading"><span className="eyebrow">DERIV MT5 / LABORATORIO</span><h1>{page==='Dashboard'?'Centro de control':page}</h1><p>Monitoreo y auditoría de decisiones con inteligencia artificial</p></div><div className="topRight"><span className={'chip '+(connected?'ok':'off')}><span className="tinyDot"/>{connected?'FastAPI conectado':error?'FastAPI sin conexión':'Consultando FastAPI'}</span><span className={'chip '+(brokerConnected?'ok':'off')}>{brokerConnected?'Deriv MT5 conectado':data?'Deriv MT5 sin conexión':'Deriv MT5 pendiente'}</span><span className="chip amber">{brokerConnected&&data?.runtime?.mode==='demo'&& Date.now()-Date.parse(data.runtime.checked_utc)<60000?'DEMO':'OBSERVACIÓN'}</span><span className="time">{updated||'Sin sincronizar'}<small>Última actualización</small></span></div></header>{error&&<div className="alert"><AlertTriangle size={19}/><span>No se pudo consultar FastAPI ({error}). Verificá que FastAPI esté iniciado en {API_BASE || window.location.origin}.</span></div>}
{page==='Dashboard'?<>{connected&&data&&!brokerConnected&&<Mt5ConnectionNotice data={data} symbol={symbol} refresh={()=>setConnectionRefresh(value=>value+1)}/>}<div className="stats">{stat('Capital de referencia',cash(initial),<Coins/>,'gold')}{stat('Balance MT5 demo',amount(balance),<Wallet/>)}{stat('P/L demo del día',amount(pnl),(pnl??0)<0?<TrendingDown/>:<TrendingUp/>,'green')}{stat('Posiciones demo',String(data?.open_positions?.length??'No disponible'),<Activity/>,'purple')}</div><MarketOverview markets={marketOverview} selected={symbol} error={marketOverviewError}
 selectMarket={showMarket}/><div className="workgrid"><div className="leftstack"><section className="panel section"><div className="sectionTitle"><Server/> Estado del sistema</div>{operationalStatus.map(({label,value,ok})=><div className="statusRow" key={label}>
<span><span className={'led '+(ok?'on':'')}/>{label}</span><span className={ok?'greenText':'muted'}>{value}</span></div>)}</section><section className="panel section"><div className="sectionTitle"><Wallet/> Presupuesto API acumulado</div>{Object.entries(budgets).map(([key,b])=><div className="budget" key={key}><div className="between"><b>{key==='openai'?'OpenAI':'Gemini'}</b><span>{b.spent===null?'Sin datos':cash(b.spent)} / {cash(b.limit)}</span></div><div className="progress"><div style={{width:`${Math.min(100,b.limit>0?((b.spent??0)+(b.reserved??0))/b.limit*100:0)}%`}}/></div><small>{b.remaining===undefined?'Consumo no medido':cash(b.remaining,4)+' disponibles · '+cash(b.reserved??0,4)+' reservados'}</small></div>)}<div className="miniNote">Presupuesto total del experimento: $5.00</div></section><section className="panel section"><div className="sectionTitle"><Clock3/> Sesión de trading</div>

<div className="statusRow"><span>Equity demo</span><b>{amount(data?.equity)}</b></div>
<div className="statusRow"><span>P/L flotante del laboratorio</span><b>{amount(data?.floating_pnl)}</b></div>
<div className="statusRow"><span>Drawdown del día</span><b>{amount(data?.daily_drawdown_usd)}</b></div>
<div className="statusRow"><span>Modo registrado</span><b>{data?.runtime?.mode??'No disponible'}</b></div>
{data?.runtime&&<p className="muted small">Último pulso {new Date(data.runtime.checked_utc).toLocaleString('es-NI',{timeZone:'America/Managua'})}</p>}
<div className="sessionHours">02:00 – 10:00 <span>America/Managua</span></div><div className="statusRow"><span>Nuevas entradas</span><span className="amberText">{data?.entries_blocked?'Bloqueo manual':data?.session_allows_entries?'Horario permitido':'Fuera de horario'}</span></div><p className="muted small">El motor demo recibe la configuración desde la consola.</p></section></div><div className={'chartArea panel'+(brokerConnected?'':' disconnectedChart')} id="grafico-mercado"><div className="chartTop"><div className="tabs">{symbols.map(m=><button key={m.symbol} className={symbol===m.symbol?'active':''} onClick={()=>setSymbol(m.symbol)}>{m.label}</button>)}</div><div className="tabs tf">{['H1','M15','M5'].map(t=><button key={t} className={tf===t?'active':''} onClick={()=>setTf(t)}>{t}</button>)}</div></div><div className="chartCaption"><div><b>{symbol}</b><span className="muted">{tf} · Gráfico de mercado</span></div><span className={"chip "+(candles.length&&!marketError?"ok":"off")}>{!brokerConnected?"MT5 SIN CONEXIÓN":marketLoading?"CARGANDO":marketError?"SIN DATOS":candles.length?`${candles.length} VELAS MT5`:"SIN COTIZACIONES"}</span></div><div className="chartPlaceholder">{candles.length>0&&!marketError?<CandleChart candles={candles} symbol={symbol}/>:<><div className="chartGrid"/><div className="chartEmpty"><ChartCandlestick size={46}/><strong>{!brokerConnected?"Gráfico en espera de MT5":marketLoading?"Cargando velas…":marketError?"No se pudieron cargar las velas":"Esperando velas de MT5"}</strong><span>{brokerConnected?marketError||'Sin velas cerradas para este mercado.':'Las velas se cargarán al conectar la cuenta demo.'}</span></div></>}</div><div className="chartFooter">{quote&&!quote.stale?'Spread '+quote.spread_points+' pts · ':quote?'Cotización obsoleta · ':'Spread no disponible · '}{marketUpdated?`Actualizado ${marketUpdated} · Horario Nicaragua · `:""} H1 <span>→</span> Tendencia <span>·</span> M15 <span>→</span> Estructura <span>·</span> M5 <span>→</span> Decisión</div></div><div className="rightstack"><section className="panel section"><div className="sectionTitle"><BrainCircuit/> Archivo histórico de Gemini</div>
{ai?.latest?<div className="aiCard">
<div className="between"><strong>{ai.latest.symbol}</strong><span className="chip">ARCHIVO</span></div>
<p className="muted small">{new Date(ai.latest.decision_time_utc).toLocaleString('es-NI',{timeZone:'America/Managua'})} · {ai.latest.model}</p>
<p className="muted small">{ai.latest.reason}</p>
<div className="miniNote">Acción histórica {ai.latest.decision} · Evaluación {ai.latest.outcome??'No disponible'}</div>
</div>:<p className="muted small">Todavía no hay decisiones históricas cargadas.</p>}</section><section className="panel section"><div className="sectionTitle"><ShieldCheck/> Protección de capital</div><div className="statusRow"><span>Riesgo por operación</span><b>0.25%</b></div><div className="statusRow"><span>Pérdida diaria máxima</span><b>1.00%</b></div><div className="statusRow"><span>Riesgo inicial nominal</span><b>$0.25</b></div><div className="statusRow"><span>SL/TP servidor</span><span className="amberText">No verificado</span></div></section></div></div><ProspectivePanel data={prospective} symbol={symbol} error={prospectiveError}/><section className="panel section researchPanel"><div className="sectionTitle"><FlaskConical/> Investigación determinista · V1.6.1 <span className="researchPill">{!researchStatus?.running?'SIN MONITOR':!brokerConnected?'EN ESPERA DE MT5':'MONITOREANDO'} · {researchStatus?.total_audits??0} auditorías</span></div><p className="muted small">H1: tendencia · M15: estructura · M5: comportamiento. Observaciones guardadas en SQLite al detectar una vela M5 cerrada. No son señales de trading ni análisis de IA.</p>{researchError&&<p className="amberText">{researchError}</p>}{researchStatus?.last_error&&<details className="researchDiagnostics"><summary>Detalle del último sondeo</summary><p className="amberText small">{researchStatus.last_error}</p></details>}<div className="miniNote">Auditoría V1.6 · validación temporal · ATR14 · EMA200 · fuerza BOS · resultados posteriores (no operaciones)</div><div className="researchList">{audits.slice(0,4).map(a=><div className="researchRow" key={'audit'+a.id}><div><b>{a.decision} · {a.context.temporal_validation}</b><small>{a.symbol} · {new Date((a.candle_time+300)*1000).toLocaleString('es-NI',{timeZone:'America/Managua'})}</small></div><div><span>ATR M5: {a.context.m5.atr14?.toFixed(5)??'—'}</span><span>EMA200 H1: {a.context.h1.ema200?.toFixed(5)??'—'}</span><span>BOS/ATR: {a.context.m15.bos_strength_atr?.toFixed(2)??'—'}</span></div><small>Horizontes evaluados: {a.outcomes.map(o=>o.horizon+' velas').join(', ')||'pendientes'}</small></div>)}</div><div className="researchList">{observations.length===0?<div className="muted small">Esperando la primera observación registrada para {symbol}...</div>:observations.map(o=><div className="researchRow" key={o.id}><div><b>{o.decision}</b><small>{new Date((o.candle_time+300)*1000).toLocaleString('es-NI',{timeZone:'America/Managua'})} · {o.symbol}</small></div><div><span>H1: {o.context.h1.trend}</span><span>M15: {o.context.m15.structure}</span><span>M5: {o.context.m5.direction}</span></div><small>{o.reason}</small></div>)}</div></section><div className="bottomgrid"><section className="panel section"><div className="sectionTitle"><History/> Operaciones recientes</div>{prospective?.demo_deals.length?<button className="navItem" onClick={()=>setPage('Operaciones')}>Ver ejecuciones demo</button>:empty('Sin operaciones demo registradas')}</section><section className="panel section"><div className="sectionTitle"><Newspaper/> Noticias económicas</div>{prospective?.news.covered?<button className="navItem" onClick={()=>setPage('Noticias')}>Ver eventos de alto impacto</button>:empty('Calendario sin cobertura')}</section><section className="panel section"><div className="sectionTitle"><BarChart3/> Métricas de investigación</div>{[['Win rate','—'],['Profit factor','—'],['Drawdown máximo','—'],['Observaciones guardadas',String(researchStatus?.total_observations??0)]].map(([k,v])=><div className="statusRow" key={k}><span>{k}</span><b>{v}</b></div>)}</section></div></>:page==='Operaciones'?<DemoPanel data={prospective}/>:page==='Reportes'?<ReportsPanel data={prospective}/>:page==='Noticias'?<NewsPanel data={prospective}/>:page==='IA y modelos'?<ProspectivePanel data={prospective} symbol={symbol} error={prospectiveError}/>:<div className="pageGrid"><section className="panel section"><div className="sectionTitle"><PlugZap/> {page}</div>{page==='Configuración'?<><EntryControls apiBase={API_BASE} blocked={data?.entries_blocked??null}/>
<p>Configuración de riesgo</p><div className="statusRow"><span>Capital inicial demo</span><b>{cash(initial)}</b></div><div className="statusRow"><span>Modo de ejecución</span><b>{data?.execution_mode??'dry-run'}</b></div><div className="statusRow"><span>Riesgo máximo por operación</span><b>0.25%</b></div><div className="statusRow"><span>Pérdida diaria máxima</span><b>1.00%</b></div></>:page==='Mercados'?<><div className="marketTiles">{symbols.map(m=><button key={m.symbol} onClick={()=>showMarket(m.symbol)}>{m.label}<small>{m.symbol} · Ver gráfico MT5</small></button>)}</div></>:page==='Investigación'?<><p>Auditoría persistente de velas M5 cerradas. Los registros se guardan en SQLite y no representan señales de compra o venta.</p><div className="statusRow"><span>Observaciones registradas</span><b>{researchStatus?.total_observations??0}</b></div><div className="statusRow"><span>Monitor</span><b>{researchStatus?.running?'Activo':'Inactivo'}</b></div><div className="statusRow"><span>Último sondeo</span><b>{researchStatus?.last_poll??'Sin datos'}</b></div>{observations.map(o=><div className="researchRow" key={o.id}><b>{o.symbol} · {o.decision}</b><span>{o.reason}</span></div>)}<div className="tabs"><a href={API_BASE+'/api/prospective/export?format=csv'}>Exportar CSV</a><a href={API_BASE+'/api/prospective/export?format=json'}>Exportar JSON</a></div><GeminiProtocolPanel/></>:<p>El módulo está listo para recibir información real del backend. No se cargarán datos inventados.</p>}{empty('Esperando integración de datos')}</section></div>}
<footer><span><ShieldCheck size={15}/> SOLO MT5 DEMO</span><span>Capital inicial: $100 · Riesgo: 0.25% · Límite diario: 1%</span><span>OpenAI $2.50 + Gemini $2.50</span></footer></div></div>}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
