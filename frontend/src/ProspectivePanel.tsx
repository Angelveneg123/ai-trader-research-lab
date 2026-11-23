import {BrainCircuit, FileText, History, Newspaper} from 'lucide-react';

type Decision = {
  symbol: string;
  m5_closed_utc: string;
  received_utc: string | null;
  provider: string;
  model: string | null;
  cycle_id: string;
  cost_usd_est: number | null;
  latency_ms: number | null;
  tokens: string | null;
  request_status: string;
  action: string | null;
  reason: string | null;
  sl: number | null;
  tp: number | null;
  outcome: string | null;
  outcome_detail: string | null;
  net_pips: number | null;
  cost_pips: number | null;
  error: string | null;
};

export type Prospective = {
  cycles: number;
  decisions: number;
  recent: Decision[];
  configured: Record<string, boolean>;
  openai_enabled: boolean;
  runtime: {mode: string; provider: string; checked_utc: string} | null;
  metrics: {positions: {symbol: string; side: string; volume: number; sl: number; tp: number}[]} | null;
  budget: Record<string, {limit: number; spent: number; reserved: number; remaining: number; attempts: number}>;
  demo: {
    updated_utc: string;
    balance_usd: number;
    realized_usd: number;
    floating_usd: number;
    positions: number;
    loss_blocked: boolean;
  } | null;
  demo_events: {recorded_utc: string; symbol: string; kind: string; detail: string}[];
  demo_deals: {ticket: number; happened_utc: string; symbol: string; entry: number;
    reason: number; volume: number; price: number; net_usd: number}[];
  reports: {local_day: string; body: string; telegram_status: string}[];
  news: {covered: boolean; source: string | null; retrieved_utc: string | null; status_by_symbol: Record<string,string|null>; events: {at_utc: string; title: string; currency: string}[]};
};

const localeDate = (value: string) =>
  new Date(value).toLocaleString('es-NI', {timeZone: 'America/Managua', dateStyle: 'short', timeStyle: 'short'});
const providerName = (value: string) => value === 'openai' ? 'OpenAI' : 'Gemini';
const money = (value: number, decimals = 2) => 'USD ' + value.toFixed(decimals);
const telegramStatus: Record<string, string> = {
  sent: 'Enviado', pending: 'Pendiente', sending: 'En proceso', rejected: 'Rechazado', unconfirmed: 'Sin confirmar',
};

export function ProspectivePanel({data, symbol, error}: {data: Prospective | null; symbol: string; error: string}) {
  return <section className="panel section researchPanel">
    <div className="sectionTitle"><BrainCircuit/> Señales prospectivas · {symbol}</div>
    {error && <p className="amberText">{error}</p>}
    {data && <p className="muted small">{data.cycles} ciclos · {data.decisions} decisiones guardadas en total · Hora de Nicaragua</p>}
    <div className="prospectiveBudget">
      {Object.entries(data?.budget ?? {}).map(([provider, values]) =>
        <div className="miniNote" key={provider}>
          <b>{providerName(provider)}</b> · {provider==='openai'&&!data?.openai_enabled?'Desactivado':data?.configured[provider]?'Clave configurada':'Clave ausente'}<br/>
          {money(values.spent, 4)} estimados + {money(values.reserved, 4)} pendientes · {money(values.remaining, 4)} disponibles de {money(values.limit)} para el experimento
        </div>)}
    </div>
    {data?.recent.length === 0 && <p className="muted">Todavía no hay consultas registradas para {symbol}.</p>}
    <div className="researchList">
      {data?.recent.map(row =>
        <div className="researchRow prospectiveRow" key={row.m5_closed_utc + row.provider}>
          <div>
            <b>{providerName(row.provider)} · {row.action ?? (row.request_status === 'error' ? 'Error' : 'En espera')}</b>
            <small>Vela {localeDate(row.m5_closed_utc)}
              {row.received_utc ? ' · Respuesta ' + localeDate(row.received_utc) : ''}</small>
            {row.model && <small>{row.model}</small>}
            <small>Ciclo {row.cycle_id}</small>
            {row.tokens && <small>Tokens entrada/salida {row.tokens} · {row.latency_ms??'—'} ms</small>}
            {row.cost_usd_est !== null && <small>Costo estimado {money(row.cost_usd_est, 6)}</small>}
          </div>
          <div>
            <span>{row.reason ?? row.error ?? 'Pendiente de respuesta'}</span>
            {row.sl !== null && row.tp !== null && <small>SL {row.sl} · TP {row.tp}</small>}
          </div>
          <div>
            <b>{row.outcome ?? 'Pendiente de evaluación'}</b>
            {row.net_pips !== null && <span>{row.net_pips.toFixed(2)} pips netos · {row.cost_pips?.toFixed(2)} pips de costo</span>}
            {row.outcome_detail && <small>{row.outcome_detail}</small>}
          </div>
        </div>)}
    </div>
  </section>;
}

export function DemoPanel({data}: {data: Prospective | null}) {
  const demo = data?.demo;
  return <section className="panel section researchPanel">
    <div className="sectionTitle"><History/> Ejecución MT5 demo</div>
    {demo ? <>
      <div className="statusRow"><span>Balance de la cuenta demo</span><b>{money(demo.balance_usd)}</b></div>
      <div className="statusRow"><span>Realizado hoy por el laboratorio</span><b>{money(demo.realized_usd)}</b></div>
      <div className="statusRow"><span>Flotante del laboratorio</span><b>{money(demo.floating_usd)}</b></div>
      <div className="statusRow"><span>Posiciones del laboratorio</span><b>{demo.positions}</b></div>
      <div className="statusRow"><span>Bloqueo de pérdida diaria</span><b>{demo.loss_blocked ? 'Activo' : 'Inactivo'}</b></div>
      <p className="muted small">Última lectura del motor demo {localeDate(demo.updated_utc)}</p>
    </> : <p className="muted">Esperando la primera lectura del motor de ejecución demo.</p>}
    {data?.metrics?.positions.map(p=><div key={p.symbol} className="statusRow">
      <span>{p.symbol} · {p.side} · {p.volume} lotes</span><b>SL {p.sl} · TP {p.tp}</b>
    </div>)}
    {!!data?.demo_deals.length && <div className="researchList">
      {data.demo_deals.map(deal =>
        <div className="researchRow" key={deal.ticket}>
          <div><b>{deal.symbol} · {deal.entry === 0 ? 'Entrada' : deal.reason === 4 ? 'Stop loss' : deal.reason === 5 ? 'Take profit' : 'Salida'}</b>
            <small>{localeDate(deal.happened_utc)} · Ticket {deal.ticket}</small></div>
          <span>{deal.volume} lotes · Precio {deal.price}</span>
          <b>{money(deal.net_usd)}</b>
        </div>)}
    </div>}
    <div className="researchList">
      {data?.demo_events.map((event, index) =>
        <div className="researchRow" key={event.recorded_utc + index}>
          <div><b>{event.symbol} · {event.kind}</b><small>{localeDate(event.recorded_utc)}</small></div>
          <span>{event.detail}</span>
        </div>)}
    </div>
  </section>;
}

export function ReportsPanel({data}: {data: Prospective | null}) {
  return <section className="panel section researchPanel">
    <div className="sectionTitle"><FileText/> Reportes de sesión</div>
    {data?.reports.length === 0 && <p className="muted">El reporte se genera después del cierre de sesión.</p>}
    {data?.reports.map(report => <details className="miniNote" key={report.local_day} open={report === data.reports[0]}>
      <summary>{report.local_day} · Telegram {telegramStatus[report.telegram_status] ?? report.telegram_status}</summary>
      <p className="sessionReport">{report.body}</p>
    </details>)}
  </section>;
}

export function NewsPanel({data}: {data: Prospective | null}) {
  return <section className="panel section researchPanel">
    <div className="sectionTitle"><Newspaper/> Calendario económico</div>
    <p className="muted">{data?.news.covered ? 'El calendario tiene cobertura para hoy.' : 'Calendario sin cobertura vigente.'}</p>
    {data?.news.source && <p className="muted small">{data.news.source} · Actualizado {data.news.retrieved_utc?localeDate(data.news.retrieved_utc):'No disponible'}</p>}
    {Object.entries(data?.news.status_by_symbol??{}).map(([symbol,issue])=><div key={symbol} className="statusRow"><span>{symbol}</span><b>{issue??'Cobertura vigente'}</b></div>)}
    {data?.news.events.map((event, index) =>
      <div className="statusRow" key={event.at_utc + index}>
        <span>{localeDate(event.at_utc)} · {event.currency}</span><b>{event.title}</b>
      </div>)}
  </section>;
}
