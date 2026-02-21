import React, { useState } from 'react'

export default function PurchaseCommandModal({ awareness, onClose }) {
  const [copied, setCopied] = useState(false)
  const purchase = awareness?.purchase || {}
  const command = purchase.purchase_command || 'maestro-purchase'
  const badge = purchase.next_node_badge || '+'

  const copyCommand = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1000)
    } catch (error) {
      console.error('Failed to copy purchase command', error)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div className="w-full h-full md:h-auto md:max-h-[85vh] md:max-w-2xl overflow-auto bg-[#05080f] border border-[#00e5ff]/30 p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <div className="text-[10px] uppercase tracking-widest font-mono text-slate-500">Node Provisioning</div>
            <h2 className="text-xl text-white uppercase tracking-widest mt-1">Project Maestro Purchase</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="border border-white/20 px-3 py-1.5 text-xs uppercase tracking-widest font-mono text-slate-300 hover:border-[#00e5ff] hover:text-[#00e5ff]"
          >
            Close
          </button>
        </div>

        <div className="border border-white/10 bg-black/40 p-4 mb-4">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Next Node Slot</div>
          <div className={`font-mono text-lg ${badge === '+$' ? 'text-amber-400' : 'text-[#00e5ff]'}`}>{badge}</div>
          <div className="text-xs text-slate-400 mt-2">
            Free remaining: {purchase.free_project_slots_remaining ?? 0} / {purchase.free_project_slots_total ?? 1}
          </div>
        </div>

        <div className="border border-white/10 bg-black/40 p-4 mb-4">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Run In A Fresh Terminal</div>
          <code className="block text-sm text-slate-100 font-mono">{command}</code>
          <button
            type="button"
            onClick={copyCommand}
            className="mt-3 border border-white/20 px-3 py-1.5 text-[10px] uppercase tracking-widest font-mono text-slate-300 hover:border-[#00e5ff] hover:text-[#00e5ff]"
          >
            {copied ? 'Copied' : 'Copy Command'}
          </button>
        </div>

        <div className="border border-white/10 bg-black/40 p-4 text-xs text-slate-400 leading-relaxed">
          This command provisions a dedicated OpenClaw project agent, captures project name and assignee, verifies card-on-file for paid slots, auto-activates Maestro licensing, and outputs the exact ingest command.
        </div>
      </div>
    </div>
  )
}
