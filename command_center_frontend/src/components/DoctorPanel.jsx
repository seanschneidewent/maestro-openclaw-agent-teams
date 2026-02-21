import React from 'react'

function CheckRow({ check }) {
  const ok = Boolean(check?.ok)
  const warning = Boolean(check?.warning)
  const marker = ok ? 'OK' : (warning ? 'WARN' : 'FAIL')
  const color = ok ? 'text-[#00e676]' : (warning ? 'text-amber-400' : 'text-rose-400')
  return (
    <div className="border border-white/10 bg-black/40 p-2 text-[11px]">
      <div className="flex items-center justify-between gap-3">
        <span className="text-slate-300 uppercase tracking-widest">{check?.name || 'check'}</span>
        <span className={`font-mono ${color}`}>{marker}</span>
      </div>
      <div className="text-slate-400 mt-1">{check?.detail || ''}</div>
    </div>
  )
}

export default function DoctorPanel({ awareness, onRun, running, report, error }) {
  const openclaw = awareness?.services?.openclaw || {}
  const gatewayAuth = openclaw?.gateway_auth || {}
  const pairing = openclaw?.device_pairing || {}
  const checks = Array.isArray(report?.checks) ? report.checks : []

  return (
    <div className="border border-white/10 bg-black/40 p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-medium tracking-[0.2em] text-white uppercase">System Doctor</h3>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">Gateway/Auth Self-Heal</p>
        </div>
        <button
          type="button"
          onClick={onRun}
          disabled={running}
          className="border border-[#00e5ff]/40 text-[#00e5ff] px-3 py-1.5 text-[10px] uppercase tracking-widest font-mono disabled:opacity-50"
        >
          {running ? 'Running...' : 'Run Doctor --fix'}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
        <div className="border border-white/10 bg-black/40 p-2">
          <div className="text-slate-500 uppercase tracking-widest text-[10px]">Auth Token</div>
          <div className={`font-mono ${gatewayAuth?.auth_token_configured ? 'text-[#00e676]' : 'text-rose-400'}`}>
            {gatewayAuth?.auth_token_configured ? 'configured' : 'missing'}
          </div>
        </div>
        <div className="border border-white/10 bg-black/40 p-2">
          <div className="text-slate-500 uppercase tracking-widest text-[10px]">Tokens Aligned</div>
          <div className={`font-mono ${gatewayAuth?.tokens_aligned ? 'text-[#00e676]' : 'text-rose-400'}`}>
            {gatewayAuth?.tokens_aligned ? 'yes' : 'no'}
          </div>
        </div>
        <div className="border border-white/10 bg-black/40 p-2">
          <div className="text-slate-500 uppercase tracking-widest text-[10px]">CLI Pairing</div>
          <div className={`font-mono ${pairing?.required ? 'text-amber-400' : 'text-[#00e676]'}`}>
            {pairing?.required ? 'required' : 'healthy'}
          </div>
        </div>
        <div className="border border-white/10 bg-black/40 p-2">
          <div className="text-slate-500 uppercase tracking-widest text-[10px]">Pending Requests</div>
          <div className="font-mono text-slate-200">{Number(pairing?.pending_requests || 0)}</div>
        </div>
      </div>

      {error && <div className="text-xs text-rose-400 mb-2">{error}</div>}
      {checks.length > 0 && (
        <div className="space-y-2 max-h-56 overflow-auto pr-1">
          {checks.map((check, idx) => (
            <CheckRow key={`${check?.name || 'check'}-${idx}`} check={check} />
          ))}
        </div>
      )}
    </div>
  )
}
