/* Integration check in a simulated DOM. Requires jsdom. */
const {JSDOM, VirtualConsole} = require(process.env.JSDOM_PATH || 'jsdom');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');

async function until(check) {
  for (let i = 0; i < 100; i++) {
    const result = check();
    if (result) return result;
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  throw new Error('El panel no mostró el dato esperado');
}

(async () => {
  const api = new URL(process.env.UI_TEST_URL || 'http://127.0.0.1:8001').origin;
  const output = process.env.UI_TEST_OUTPUT || 'evidencias';
  const disconnected = process.env.UI_TEST_DISCONNECTED === '1';
  const marketRequests = [];
  const response = await fetch(api + '/api/prospective?symbol=EURUSDmicro');
  assert.equal(response.status, 200);
  const p = await response.json();
  const row = p.recent[0];
  assert.equal(row.action, 'WAIT');
  assert.equal(row.symbol, 'EURUSDmicro');
  const consoleSink = new VirtualConsole();
  const errors = [];
  consoleSink.on('jsdomError', e => errors.push(e.message));
  const home = await fetch(api + '/');
  assert.equal(home.status, 200);
  const html = await home.text();
  const scriptURL = new URL(html.match(/src="(\/assets\/[^"]+\.js)"/)[1], api);
  const script = await fetch(scriptURL);
  assert.equal(script.status, 200);
  const cssURL = new URL(html.match(/href="(\/assets\/[^"]+\.css)"/)[1], api);
  assert.equal((await fetch(cssURL)).status, 200);
  console.log('HTTP 200 | Panel, JavaScript y CSS en el mismo origen.');
  const dom = new JSDOM(html, {url: api + '/', runScripts:'outside-only',
    pretendToBeVisual:true, virtualConsole:consoleSink,
    beforeParse(window) {
      window.fetch = (url, init) => {
        const request = new URL(url, window.location.href);
        assert.equal(request.origin, api);
        if (request.pathname === '/api/market/candles') marketRequests.push(request.href);
        return globalThis.fetch(request, init);
      };
      window.AbortController = globalThis.AbortController;
    }});
  try {
    dom.window.eval(await script.text());
    const body = dom.window.document.body;
    const button = await until(() => [...body.querySelectorAll('button')].find(b => b.textContent.trim()==='IA y modelos'));
    const marketsResponse = await fetch(api + '/api/prospective/markets');
    assert.equal(marketsResponse.status, 200);
    const {markets} = await marketsResponse.json();
    assert.deepEqual(markets.map(item=>item.symbol), ['EURUSDmicro', 'USDJPYmicro', 'XAUUSDmicro']);
    const overview = await until(() => {
      const region = body.querySelector('.marketOverview');
      return region && region.querySelectorAll('article').length === 3 && region;
    });
    const cards = [...overview.querySelectorAll('article')];
    for (const [index, card] of cards.entries()) {
      assert.ok(card.textContent.includes(markets[index].latest.cycle_id));
      assert.equal(card.querySelector('.marketOverviewStatus').textContent, 'WAIT');
    }
    fs.writeFileSync(path.join(output, 'mercados_http_simulado.json'), JSON.stringify({tipo:'SIMULADA', http:200, markets},null,2));
    fs.writeFileSync(path.join(output, 'mercados_panel_simulado.txt'), overview.textContent + '\n');
    const chart = body.querySelector('#grafico-mercado');
    assert.deepEqual([...chart.querySelector('.tabs').querySelectorAll('button')].map(b=>b.textContent),
      ['EUR/USD','USD/JPY','XAU/USD']);
    await until(()=>body.textContent.includes('FastAPI conectado'));
    if (disconnected) {
      const notice = await until(()=>body.querySelector('.connectionNotice'));
      assert.ok(notice.textContent.includes('Deriv MT5 sin conexión'));
      assert.ok(notice.textContent.includes('-10005'));
      assert.match(chart.textContent, /Gráfico en espera de MT5/);
      assert.equal(marketRequests.length, 0);
      const response = await fetch(api + '/api/dashboard');
      const dashboard = await response.json();
      assert.equal(dashboard.mt5_error_code, 'IPC_TIMEOUT');
      assert.equal(dashboard.mt5_native_code, -10005);
      assert.equal(dashboard.current_balance, null);
      console.log('SIMULADA | FastAPI conectado, MT5 IPC_TIMEOUT y gráfico en espera sin peticiones de velas.');
      fs.writeFileSync(path.join(output, 'mt5_dashboard_sin_conexion.txt'), notice.textContent.trim()+'\n'+chart.textContent.trim()+'\n');
    } else {
      await until(()=>marketRequests.length > 0 && chart.textContent.includes('VELAS MT5'));
      assert.ok(marketRequests.every(url=>url.includes('include_quote=true')));
      assert.ok(body.textContent.includes('Deriv MT5 conectado'));
      assert.equal(body.querySelector('.connectionNotice'), null);
      console.log('SIMULADA | Gráfico con velas y cotización en la misma solicitud. Tres selectores.');
    }
    for (const index of [1, 2, 0]) {
      const selectMarket = cards[index].querySelector('button');
      selectMarket.click();
      const symbol = markets[index].symbol;
      await until(() => selectMarket.getAttribute('aria-pressed') === 'true'
        && (disconnected || chart.querySelector(`svg[aria-label="Gráfico de velas ${symbol}"]`)));
    }
    console.log('SIMULADA | Tres ciclos distintos en SQLite y selección de los tres mercados en React.');
    button.click();
    await until(() => body.textContent.includes('Ciclo ' + row.cycle_id)
          && body.textContent.includes('Gemini · WAIT')
          && body.textContent.includes('Fixture de interfaz y SQLite'));
    assert.deepEqual(errors, []);
    const section = [...body.querySelectorAll('section')].find(s=>s.textContent.includes('Ciclo ' + row.cycle_id));
    fs.writeFileSync(path.join(output, '02_dom_simulado.txt'), section.textContent + '\n');
    fs.writeFileSync(path.join(output, '02_http_simulado.json'), JSON.stringify({tipo:'SIMULADA', http:200, row},null,2));
    console.log('SIMULADA | HTTP 200 | SQLite → FastAPI → React');
    console.log('Ciclo', row.cycle_id, 'Vela UTC', row.m5_closed_utc, 'Respuesta UTC', row.received_utc);
  } finally {
    dom.window.close();
  }
  const after = await (await fetch(api + '/api/research/status')).json();
  assert.equal(after.running, true);
  console.log('El observador FastAPI sigue activo al cerrar el DOM. Último sondeo', after.last_poll);
})().catch(error => {console.error(error);process.exitCode=1;});
