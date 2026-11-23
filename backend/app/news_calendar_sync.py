"""Read-only economic-calendar downloader. Fails closed; never invents events."""
import argparse
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
COUNTRY_TO_CURRENCY = {'US': 'USD', 'USA': 'USD', 'United States': 'USD',
                       'EU': 'EUR', 'EA': 'EUR', 'EMU': 'EUR', 'Euro Area': 'EUR',
                       'Eurozone': 'EUR', 'JP': 'JPY', 'Japan': 'JPY'}


def normalize_finnhub(data, start, end):
    if not isinstance(data, dict) or not isinstance(data.get('economicCalendar'), list):
        raise ValueError('Respuesta del calendario sin economicCalendar válido')
    events = []
    for item in data['economicCalendar']:
        if not isinstance(item, dict):
            raise ValueError('Evento mal formado')
        country = item.get('country')
        if country not in COUNTRY_TO_CURRENCY:
            continue
        currency = COUNTRY_TO_CURRENCY[country]
        impact = item.get('impact')
        # Finnhub impact commonly uses numeric 1/2/3; unknown values must not be guessed.
        if isinstance(impact, bool) or impact not in (1, 2, 3):
            raise ValueError('Impacto desconocido para ' + currency)
        raw_time = item.get('time')
        if not isinstance(raw_time, str):
            raise ValueError('Fecha inválida para ' + currency)
        try:
            at = datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('Fecha no ISO del proveedor; revisar adaptador') from exc
        if at.tzinfo is None:
            raise ValueError('Fecha sin zona horaria: se rechaza para evitar desfase')
        at = at.astimezone(UTC)
        title = item.get('event')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Evento sin título')
        if start <= at <= end:
            events.append({'at_utc': at.isoformat(), 'currency': currency,
                           'impact': {1: 'low', 2: 'medium', 3: 'high'}[impact],
                           'title': title[:200]})
    return events


def sync(token, output, now=None, opener=None):
    if not token:
        raise ValueError('Falta FINNHUB_API_KEY')
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('Se requiere hora UTC')
    now = now.astimezone(UTC)
    start, end = now - timedelta(hours=1), now + timedelta(days=2)
    params = urllib.parse.urlencode({'from': start.date().isoformat(), 'to': end.date().isoformat()})
    url = 'https://finnhub.io/api/v1/calendar/economic?' + params
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'X-Finnhub-Token': token})
    try:
        with opener(request, timeout=10) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Finnhub HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Finnhub sin respuesta') from None
    events = normalize_finnhub(data, start, end)
    # A successful response with zero relevant events cannot prove complete coverage.
    if not events:
        raise ValueError('Sin eventos verificables: calendario anterior sin modificar')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {'coverage_start_utc': start.isoformat(), 'coverage_end_utc': end.isoformat(),
               'events': events, 'source': 'Finnhub economic calendar',
               'retrieved_utc': now.isoformat(), 'coverage_verified': False}
    # Write atomically: invalid HTTP responses never replace last valid file.
    fd, tmp = tempfile.mkstemp(prefix='.calendar_', suffix='.json', dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return len(events)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/news_calendar_candidate.json')
    args = parser.parse_args()
    try:
        count = sync(os.getenv('FINNHUB_API_KEY', ''), args.output)
        print(f'Candidato actualizado: {count} eventos. Cobertura aún sin certificar.')
    except Exception as exc:
        parser.exit(1, f'Calendario NO actualizado: {exc}\n')
