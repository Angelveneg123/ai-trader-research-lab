const {chromium} = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 960}});
    const response = await fetch('http://127.0.0.1:8001/api/prospective?symbol=EURUSDmicro');
    assert.equal(response.status, 200);
    const p = await response.json();
    const row = p.recent[0];
    assert.equal(row.action, 'WAIT');
    assert.equal(row.symbol, 'EURUSDmicro');
    await page.goto('http://127.0.0.1:5173/', {waitUntil:'networkidle'});
    await page.getByRole('button', {name: 'IA y modelos', exact: true}).click();
    await page.getByText('Ciclo ' + row.cycle_id, {exact:true}).waitFor();
    await page.getByText('Gemini · WAIT', {exact:true}).waitFor();
    await page.getByText('Fixture de interfaz y SQLite', {exact:true}).waitFor();
    await page.addStyleTag({content: 'body::after{content:"EVIDENCIA SIMULADA · SIN MT5 EXTERNO";position:fixed;bottom:14px;right:16px;background:#162c41;color:#fff;padding:10px;border-radius:8px;z-index:1000;font:bold 14px sans-serif}'});
    await page.screenshot({path: 'evidencias/02_panel_simulado.png', fullPage:true});
    console.log('SIMULADA | HTTP 200 | React muestra el mismo identificador de ciclo y respuesta WAIT.');
    console.log('Ciclo', row.cycle_id, 'Vela UTC', row.m5_closed_utc, 'Respuesta UTC', row.received_utc);
    fs.writeFileSync('evidencias/02_http_simulado.json', JSON.stringify({tipo:'SIMULADA', http:200, row},null,2));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
