import React from 'react'

export function DrawerCard({ title, children, className = '' }) {
  return (
    <section className={`border border-white/10 bg-black/40 p-4 ${className}`}>
      <h3 className="text-xs uppercase tracking-widest font-mono text-[#00e5ff] mb-3">{title}</h3>
      {children}
    </section>
  )
}

export function EmptyState() {
  return <div className="text-sm text-slate-500">No data available.</div>
}

export function listOrEmpty(items, renderFn) {
  if (!Array.isArray(items) || items.length === 0) {
    return <EmptyState />
  }
  return <div className="space-y-2">{items.map(renderFn)}</div>
}

