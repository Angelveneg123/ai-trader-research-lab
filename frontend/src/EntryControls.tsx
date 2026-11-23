import {useState} from 'react';

export function EntryControls({apiBase, blocked}: {apiBase: string; blocked: boolean | null}) {
  const [token, setToken] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  async function change(value: boolean) {
    setPending(true);
    setMessage('');
    try {
      const result = await fetch(apiBase + '/api/controls/entries', {
        method: 'POST',
        headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
        body: JSON.stringify({blocked: value}),
      });
      const data = await result.json();
      if (!result.ok) throw new Error(data.detail ?? 'El control no respondió');
      setMessage(data.blocked ? 'Entradas bloqueadas. El supervisor continúa.' : 'Bloqueo manual retirado.');
      setToken('');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
    }
  }
  return <div className="entryControls">
    <div className="statusRow"><span>Bloqueo manual</span><b>{blocked === null ? 'Sin registro' : blocked ? 'Activo' : 'Inactivo'}</b></div>
    <label>Token local de control <input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}/></label>
    <div className="tabs">
      <button disabled={!token || pending} onClick={() => change(true)}>Bloquear nuevas entradas</button>
      <button disabled={!token || pending} onClick={() => change(false)}>Retirar bloqueo manual</button>
    </div>
    {message && <p role="status" className="muted small">{message}</p>}
  </div>;
}
