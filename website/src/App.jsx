import React, { useState } from 'react';
import {
  Terminal,
  Copy,
  Check,
  Smartphone,
  FileSearch,
  Activity,
  ServerCrash,
  HardHat,
  ChevronRight,
  Cpu
} from 'lucide-react';

export default function App() {
  const [copied, setCopied] = useState(false);
  const installCommand = "curl -fsSL https://maestro-billing-service-production.up.railway.app/install | bash";

  const handleCopy = () => {
    navigator.clipboard.writeText(installCommand);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen bg-[#020617] text-slate-300 font-sans selection:bg-cyan-900 selection:text-cyan-100">

      {/* Blueprint Grid Background */}
      <div className="fixed inset-0 pointer-events-none opacity-[0.03] z-0"
           style={{ backgroundImage: 'linear-gradient(#38bdf8 1px, transparent 1px), linear-gradient(90deg, #38bdf8 1px, transparent 1px)', backgroundSize: '40px 40px' }}>
      </div>

      {/* Top Status Bar (Industrial Vibe) */}
      <div className="relative z-10 border-b-2 border-slate-800 bg-[#020617]">
        <div className="max-w-7xl mx-auto px-6 h-12 flex items-center justify-between font-mono text-xs text-slate-500 uppercase tracking-widest">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse"></div> SYS_STATUS: ONLINE</span>
            <span className="hidden sm:inline border-l border-slate-800 pl-4">ENV: LOCAL_RUNTIME</span>
          </div>
          <div>MAESTRO_SOLO // V1.0.0</div>
        </div>
      </div>

      {/* Main Container */}
      <main className="relative z-10 max-w-7xl mx-auto px-6 py-12 md:py-24 grid lg:grid-cols-12 gap-12 lg:gap-8">

        {/* Left Column: The Pitch */}
        <div className="lg:col-span-5 flex flex-col justify-center">
          <div className="mb-8">
            <div className="inline-block border border-cyan-900 bg-cyan-950/30 text-cyan-400 px-3 py-1 font-mono text-xs uppercase tracking-wider mb-6">
              Deployment Directive
            </div>
            <h1 className="text-5xl md:text-6xl font-black text-white leading-[1.1] mb-6 uppercase tracking-tight">
              Hardware-Locked <br/>
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400">
                Site Intelligence.
              </span>
            </h1>
            <p className="text-lg text-slate-400 leading-relaxed mb-8 border-l-2 border-slate-800 pl-4">
              Stop fighting schedule drift and searching 500-page plan sets. Deploy a local, always-on AI agent to your trailer. Interrogate specs, enforce scope, and command your site via text.
            </p>
          </div>

          <div className="flex flex-col gap-4 font-mono text-sm border-t border-slate-800 pt-8">
            <div className="flex items-center gap-3 text-slate-300">
              <Cpu className="w-5 h-5 text-blue-500" /> Openclaw-powered local RAG
            </div>
            <div className="flex items-center gap-3 text-slate-300">
              <ServerCrash className="w-5 h-5 text-blue-500" /> Zero cloud dependency (100% Isolated)
            </div>
            <div className="flex items-center gap-3 text-slate-300">
              <HardHat className="w-5 h-5 text-blue-500" /> GC & Superintendent focused
            </div>
          </div>
        </div>

        {/* Right Column: The Terminal Hero */}
        <div className="lg:col-span-7 flex flex-col justify-center">
          <div className="bg-[#0a0f1c] border border-slate-700/50 rounded-lg shadow-2xl shadow-blue-900/20 overflow-hidden">
            {/* Terminal Header */}
            <div className="bg-slate-900/80 border-b border-slate-800 px-4 py-3 flex items-center justify-between">
              <div className="flex gap-2">
                <div className="w-3 h-3 rounded-full bg-slate-700"></div>
                <div className="w-3 h-3 rounded-full bg-slate-700"></div>
                <div className="w-3 h-3 rounded-full bg-slate-700"></div>
              </div>
              <div className="font-mono text-xs text-slate-500">trailer-host-01 ~ bash</div>
              <div className="w-9"></div> {/* spacer */}
            </div>

            {/* Terminal Body */}
            <div className="p-6 md:p-8 font-mono text-sm md:text-base">
              <div className="mb-4 text-slate-500 flex gap-2">
                <ChevronRight className="w-5 h-5 text-cyan-500 shrink-0" />
                <span className="text-slate-400">Initialize Maestro Solo local runtime. Requires root privileges for environment setup.</span>
              </div>

              <div className="bg-[#0f172a] border border-blue-900/30 p-4 rounded mb-6 flex flex-col gap-4">
                <code className="text-blue-300 break-all leading-relaxed">
                  {installCommand}
                </code>
              </div>

              <div className="flex flex-col sm:flex-row gap-4 items-center justify-between mt-8 border-t border-slate-800/50 pt-6">
                <span className="text-xs text-slate-500 uppercase tracking-wider hidden sm:block">Action Required //</span>
                <button
                  onClick={handleCopy}
                  className="w-full sm:w-auto flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded uppercase font-bold tracking-wider transition-all"
                >
                  {copied ? <Check className="w-5 h-5" /> : <Copy className="w-5 h-5" />}
                  {copied ? 'Command Copied' : 'Copy Install Script'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Spec Sheet Section */}
      <section className="relative z-10 border-t-2 border-slate-800 bg-[#020617]">
        <div className="max-w-7xl mx-auto px-6 py-24">
          <h2 className="text-3xl font-bold uppercase tracking-tight text-white mb-16 border-l-4 border-blue-500 pl-4">
            System Capabilities
          </h2>

          <div className="space-y-12">

            {/* Spec 01 */}
            <div className="grid md:grid-cols-12 gap-6 items-start">
              <div className="md:col-span-3 font-mono text-5xl font-black text-slate-800">
                01.
              </div>
              <div className="md:col-span-9 border border-slate-800 bg-slate-900/20 p-8 rounded hover:border-blue-900 transition-colors relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-10">
                  <Smartphone className="w-24 h-24" />
                </div>
                <h3 className="text-2xl font-bold text-white mb-4 uppercase">Asynchronous Field Comms</h3>
                <p className="text-slate-400 text-lg mb-6 leading-relaxed max-w-3xl">
                  You aren't at your desk. You're putting out fires in the dirt. Text your Maestro agent directly from your phone to update the schedule, draft an RFI, or log a delay. It parses natural language and updates the project state instantly.
                </p>
                <div className="font-mono text-sm text-cyan-500 bg-cyan-950/20 px-4 py-2 inline-block border border-cyan-900/50">
                  ENGINE: Asynchronous webhook integration ensures constant uptime.
                </div>
              </div>
            </div>

            {/* Spec 02 */}
            <div className="grid md:grid-cols-12 gap-6 items-start">
              <div className="md:col-span-3 font-mono text-5xl font-black text-slate-800">
                02.
              </div>
              <div className="md:col-span-9 border border-slate-800 bg-slate-900/20 p-8 rounded hover:border-blue-900 transition-colors relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-10">
                  <FileSearch className="w-24 h-24" />
                </div>
                <h3 className="text-2xl font-bold text-white mb-4 uppercase">Plan Set Interrogation</h3>
                <p className="text-slate-400 text-lg mb-6 leading-relaxed max-w-3xl">
                  Stop searching. Start asking. Keyword searching massive PDFs is obsolete. Upload your plans and specs, and ask: <span className="text-white">"What's the exact spec for the rebar on the north retaining wall?"</span> Maestro pulls the detail and cites the page.
                </p>
                <div className="font-mono text-sm text-cyan-500 bg-cyan-950/20 px-4 py-2 inline-block border border-cyan-900/50">
                  ENGINE: Local RAG and custom supercharged tool calling via Maestro.
                </div>
              </div>
            </div>

            {/* Spec 03 */}
            <div className="grid md:grid-cols-12 gap-6 items-start">
              <div className="md:col-span-3 font-mono text-5xl font-black text-slate-800">
                03.
              </div>
              <div className="md:col-span-9 border border-slate-800 bg-slate-900/20 p-8 rounded hover:border-blue-900 transition-colors relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-10">
                  <Activity className="w-24 h-24" />
                </div>
                <h3 className="text-2xl font-bold text-white mb-4 uppercase">State & Schedule Guardrails</h3>
                <p className="text-slate-400 text-lg mb-6 leading-relaxed max-w-3xl">
                  This isn't a static Gantt chart. Maestro actively monitors submittals, parses daily logs, and flags bottlenecks before they happen. If a sub pushes framing back two days, Maestro instantly calculates the cascading delays.
                </p>
                <div className="font-mono text-sm text-cyan-500 bg-cyan-950/20 px-4 py-2 inline-block border border-cyan-900/50">
                  ENGINE: Real-time state reconciliation matrix.
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* Architecture Block */}
      <section className="relative z-10 border-t-2 border-b-2 border-slate-800 bg-slate-900/50">
        <div className="max-w-7xl mx-auto px-6 py-24">
          <div className="grid lg:grid-cols-2 gap-16 items-center">

            {/* Visual Schematic */}
            <div className="order-2 lg:order-1 border-2 border-slate-800 p-6 bg-[#020617] relative">
              <div className="absolute top-0 left-0 px-2 py-1 bg-slate-800 text-xs font-mono uppercase text-slate-400 -translate-y-full">Fig 1. Local Architecture</div>
              <div className="border border-blue-900/50 p-8 text-center space-y-6 relative overflow-hidden">
                <div className="font-mono text-cyan-500 border border-cyan-900/50 bg-cyan-950/20 py-3">YOUR HARDWARE</div>
                <div className="flex justify-center">
                  <div className="h-8 w-px bg-slate-700"></div>
                </div>
                <div className="font-mono text-white border-2 border-blue-600 bg-blue-900/20 py-6 px-4">
                  <span className="block mb-2 text-blue-400 text-sm">OPENCLAW RUNTIME</span>
                  <span className="text-2xl font-bold">MAESTRO AGENT</span>
                </div>
                <div className="flex justify-between items-center px-4 font-mono text-xs text-slate-500 pt-4 border-t border-slate-800 mt-4">
                  <span>// ISOLATED</span>
                  <span>// SECURE</span>
                  <span>// ZERO-CLOUD</span>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="order-1 lg:order-2">
              <h2 className="text-3xl font-bold uppercase tracking-tight text-white mb-6">
                Absolute Data Sovereignty.
              </h2>
              <p className="text-slate-400 text-lg mb-6 leading-relaxed">
                Commercial builds involve strict NDAs, proprietary financials, and sensitive architectural data. Uploading your site's brain to a public cloud LLM is a non-starter.
              </p>
              <p className="text-slate-400 text-lg leading-relaxed mb-8">
                Maestro Solo turns your hardware into the server. The intelligence lives entirely on your machine, walled off from the outside world. Security isn't a feature; it's the foundation.
              </p>
              <div className="inline-flex items-center gap-2 font-mono text-blue-400 border-b border-blue-400 pb-1 uppercase tracking-wider text-sm">
                <Terminal className="w-4 h-4" /> Deploy locally via Terminal
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* Footer / Fleet Teaser */}
      <footer className="relative z-10 bg-[#020617] pt-24 pb-12 px-6 text-center">
        <h2 className="text-2xl md:text-3xl font-bold uppercase tracking-tight text-slate-300 mb-4">
          Start Solo. Scale to the Fleet.
        </h2>
        <p className="text-slate-500 max-w-2xl mx-auto mb-12">
          Maestro Solo equips the individual Superintendent today. Coming soon: <span className="text-blue-400">Maestro Fleet</span>—the enterprise command center connecting every local site server back to the home office.
        </p>

        <div className="border-t border-slate-800 pt-12 flex flex-col md:flex-row items-center justify-between max-w-7xl mx-auto font-mono text-xs text-slate-600">
          <div>&copy; {new Date().getFullYear()} MAESTRO SYSTEMS.</div>
          <div className="mt-4 md:mt-0">BUILT FOR THE DIRT.</div>
        </div>
      </footer>
    </div>
  );
}
