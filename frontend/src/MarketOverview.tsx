import {ChartCandlestick} from 'lucide-react';

type MarketCycle = {
  cycle_id: string;
  m5_closed_utc: string;
  spread_pips: number | null;
  request_status: string | null;
  received_utc: string | null;
  action: string | null;
  reason: string | null;
  error: string | null;
  model: string | null;
  cost_usd_est: number | null;
};

export type MarketSummary = {label: string; symbol: string; latest: MarketCycle | null};

const timeInNicaragua = (utc: string) =>
  new Date(utc).toLocaleString('es-NI', {
    timeZone: 'America/Managua', dateStyle: 'short', timeStyle: 'short',
  });

export function MarketOverview({markets, selected, error, selectMarket}: {
  markets: MarketSummary[] | null;
  selected: string;
  error: string;
  selectMarket: (symbol: string) => void;
}) {
  return <section className="panel section researchPanel marketOverview" aria-label="Resumen de los tres mercados">
    <div className="sectionTitle"><ChartCandlestick/> Observación por mercado</div>
    {error && <p role="status" className="amberText small">Resumen sin actualizar · {error}</p>}
    {!markets && !error && <p className="muted small">Cargando ciclos de observación…</p>}
    <div className="marketOverviewGrid">
      {markets?.map(({label, symbol, latest}) => {
        const status = latest?.action
          ?? (latest?.error || latest?.request_status === 'error' ? 'Error de Gemini'
            : latest?.request_status === 'reserved' ? 'Consulta pendiente'
              : latest ? 'Vela sin respuesta de Gemini' : 'Sin ciclo registrado');
        return <article key={symbol} className={symbol === selected ? 'marketOverviewCard selectedMarket' : 'marketOverviewCard'}>
          <div className="between">
            <h3>{label}</h3>
            <span className="muted small">{symbol}</span>
          </div>
          <p className="marketOverviewStatus">{status}</p>
          {latest && <>
            <dl>
              <div><dt>Vela M5 cerrada</dt><dd>{timeInNicaragua(latest.m5_closed_utc)}</dd></div>
              {latest.received_utc && <div><dt>Respuesta de Gemini</dt><dd>{timeInNicaragua(latest.received_utc)}</dd></div>}
              {latest.spread_pips !== null && <div><dt>Spread de la captura</dt><dd>{latest.spread_pips.toFixed(2)} pips</dd></div>}
              {latest.cost_usd_est !== null && <div><dt>Costo estimado</dt><dd>USD {latest.cost_usd_est.toFixed(6)}</dd></div>}
            </dl>
            {(latest.reason || latest.error) && <p className="muted small">{latest.reason ?? latest.error}</p>}
            <small className="muted marketOverviewCycle">Ciclo {latest.cycle_id}</small>
          </>}
          <button className="navItem marketOverviewButton" type="button" onClick={() => selectMarket(symbol)}
                  aria-label={'Ver gráfico e historial de ' + symbol} aria-pressed={symbol === selected}>
            Ver gráfico e historial
          </button>
        </article>;
      })}
    </div>
    {!!markets?.length && <p className="muted small">Último ciclo guardado por mercado · Hora de Nicaragua</p>}
  </section>;
}
