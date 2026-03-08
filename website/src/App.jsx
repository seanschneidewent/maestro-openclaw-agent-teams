import React, { useEffect, useRef, useState } from 'react';
import {
  Search,
  Layers,
  CalendarClock,
  MessageSquare,
  Network,
  ArrowRight,
  ExternalLink,
  ArrowUpRight,
  Crosshair,
  Cpu,
  Eye,
  Wrench,
  HardDrive,
  Mail,
  Calendar,
  CheckCircle2,
  Building2,
  Flame,
  Mountain,
  Hammer,
  Menu,
  X,
} from 'lucide-react';

const cleanText = (value) => (typeof value === 'string' ? value.trim() : '');

const externalLinkProps = (href) => {
  if (!href || href.startsWith('#') || href.startsWith('/') || href.startsWith('mailto:')) {
    return {};
  }

  return {
    target: '_blank',
    rel: 'noreferrer',
  };
};

function loadCalendlyScript() {
  if (typeof window === 'undefined') {
    return Promise.resolve();
  }

  const existingStylesheet = document.querySelector('link[data-calendly-widget-style="true"]');
  if (!existingStylesheet) {
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = 'https://assets.calendly.com/assets/external/widget.css';
    stylesheet.dataset.calendlyWidgetStyle = 'true';
    document.head.appendChild(stylesheet);
  }

  if (window.Calendly) {
    return Promise.resolve(window.Calendly);
  }

  return new Promise((resolve, reject) => {
    const existingScript = document.querySelector('script[data-calendly-widget="true"]');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(window.Calendly), { once: true });
      existingScript.addEventListener('error', reject, { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://assets.calendly.com/assets/external/widget.js';
    script.async = true;
    script.dataset.calendlyWidget = 'true';
    script.onload = () => resolve(window.Calendly);
    script.onerror = reject;
    document.body.appendChild(script);
  });
}

function CtaLink({
  href,
  children,
  className = '',
  disabledClassName = 'cursor-not-allowed opacity-50',
}) {
  const enabled = Boolean(href);

  return (
    <a
      href={enabled ? href : undefined}
      aria-disabled={!enabled}
      {...externalLinkProps(href)}
      className={`${className} ${enabled ? '' : disabledClassName}`.trim()}
    >
      {children}
    </a>
  );
}

function FooterLinks() {
  return (
    <div className="mt-4 flex flex-wrap items-center justify-center gap-4 text-xs font-medium text-zinc-400 md:mt-0">
      <a href="/built-for" className="transition-colors hover:text-zinc-700">Built For</a>
      <a href="/privacy" className="transition-colors hover:text-zinc-700">Privacy</a>
      <a href="/terms" className="transition-colors hover:text-zinc-700">Terms</a>
      <a href="/refund" className="transition-colors hover:text-zinc-700">Refunds</a>
    </div>
  );
}

function EmailSignupSection() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState('idle');
  const [errorMessage, setErrorMessage] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;

    setStatus('submitting');
    setErrorMessage('');

    try {
      const response = await fetch('/api/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: trimmed }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Something went wrong.');
      }

      setStatus('success');
      setEmail('');
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Unable to subscribe. Please try again.');
      setStatus('error');
    }
  };

  return (
    <section className="border-t border-zinc-200 bg-zinc-50">
      <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
        <div className="mx-auto max-w-xl text-center">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-cyan-200/70 bg-white px-3.5 py-1.5 text-sm font-medium text-zinc-700 shadow-[0_0_15px_rgba(6,182,212,0.08)]">
            <Mail className="h-4 w-4 text-cyan-600" />
            Stay updated
          </div>
          <h2 className="mb-4 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
            Get notified when we ship.
          </h2>
          <p className="mb-10 text-lg leading-relaxed text-zinc-700">
            Product updates, deployment stories, and the occasional field note. No spam.
          </p>

          {status === 'success' ? (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-6 py-5">
              <p className="font-semibold text-emerald-900">You&apos;re on the list.</p>
              <p className="mt-1 text-sm text-emerald-700">We&apos;ll be in touch when there&apos;s something worth sharing.</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
              <input
                type="email"
                required
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="flex-1 rounded-xl border border-zinc-200 bg-white px-5 py-3.5 text-base text-zinc-950 placeholder:text-zinc-400 shadow-sm outline-none transition-all focus:border-cyan-400 focus:shadow-[0_0_0_3px_rgba(6,182,212,0.1)]"
              />
              <button
                type="submit"
                disabled={status === 'submitting'}
                className="rounded-xl bg-zinc-950 px-7 py-3.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_15px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.4)] disabled:opacity-50 disabled:hover:translate-y-0"
              >
                {status === 'submitting' ? 'Subscribing\u2026' : 'Subscribe'}
              </button>
            </form>
          )}

          {status === 'error' ? (
            <p className="mt-4 text-sm font-medium text-red-600">{errorMessage}</p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function MobileNav({ primaryContactHref }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const navLinks = [
    { href: '#how-it-works', label: 'How It Works' },
    { href: '#the-fleet', label: 'The Fleet' },
    { href: '/built-for', label: 'Built For' },
    { href: '#get-started', label: 'Pricing' },
  ];

  return (
    <nav className="sticky top-0 z-50 border-b border-zinc-200/50 bg-white/60 backdrop-blur-2xl transition-all duration-300">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <div className="group flex cursor-pointer items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-950 shadow-[0_0_15px_rgba(6,182,212,0.3)] transition-all group-hover:bg-zinc-900 group-hover:shadow-[0_0_20px_rgba(6,182,212,0.5)]">
            <span className="font-mono text-xs font-bold tracking-wider text-cyan-400">MF</span>
          </div>
          <span className="font-semibold tracking-tight text-zinc-950">Maestro Fleet</span>
        </div>

        <div className="hidden items-center gap-8 text-sm font-medium text-zinc-500 md:flex">
          {navLinks.map(({ href, label }) => (
            <a key={label} href={href} className="transition-colors hover:text-zinc-950">{label}</a>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <CtaLink
            href="#get-started"
            className="hidden rounded-lg bg-zinc-950 px-5 py-2.5 text-sm font-medium text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_15px_rgba(6,182,212,0.2)] transition-all duration-300 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.4)] sm:inline-flex"
          >
            Get Started
          </CtaLink>
          <button
            type="button"
            onClick={() => setMobileOpen((prev) => !prev)}
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-zinc-700 transition-colors hover:bg-zinc-100 md:hidden"
            aria-label="Toggle navigation menu"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {mobileOpen ? (
        <div className="border-t border-zinc-200/60 bg-white/95 backdrop-blur-xl md:hidden">
          <div className="mx-auto max-w-6xl space-y-1 px-6 py-4">
            {navLinks.map(({ href, label }) => (
              <a
                key={label}
                href={href}
                onClick={() => setMobileOpen(false)}
                className="block rounded-lg px-4 py-3 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 hover:text-zinc-950"
              >
                {label}
              </a>
            ))}
            <div className="pt-2">
              <CtaLink
                href={primaryContactHref}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-950 px-6 py-3.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_15px_rgba(6,182,212,0.2)] transition-all hover:bg-zinc-900"
              >
                <Calendar className="h-4 w-4 text-cyan-400" />
                Book a Consultation
                <ArrowUpRight className="h-4 w-4 text-cyan-400" />
              </CtaLink>
            </div>
          </div>
        </div>
      ) : null}
    </nav>
  );
}

function PageShell({
  eyebrow,
  title,
  intro,
  children,
  primaryAction,
  secondaryAction,
  wrapChildren = true,
  contentClassName = '',
  mainClassName = 'mx-auto max-w-5xl px-6 py-20 md:py-28',
}) {
  return (
    <div className="min-h-screen bg-white text-zinc-800 antialiased selection:bg-cyan-100 selection:text-cyan-900">
      <div className="border-b border-zinc-200/70 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <a href="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-950 shadow-[0_0_15px_rgba(6,182,212,0.3)]">
              <span className="font-mono text-xs font-bold tracking-wider text-cyan-400">MF</span>
            </div>
            <span className="font-semibold tracking-tight text-zinc-950">Maestro Fleet</span>
          </a>
          <FooterLinks />
        </div>
      </div>

      <main className={mainClassName}>
        <div className="max-w-3xl">
          <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.25)]">
            {eyebrow}
          </p>
          <h1 className="mb-6 text-4xl font-bold leading-tight tracking-tight text-zinc-950 md:text-5xl">{title}</h1>
          {intro ? <p className="mb-10 text-lg leading-relaxed text-zinc-700">{intro}</p> : null}
        </div>

        {wrapChildren ? (
          <div
            className={[
              'rounded-3xl border border-zinc-200/80 bg-zinc-50 p-8 shadow-[0_12px_30px_-20px_rgba(0,0,0,0.08)] md:p-10',
              contentClassName,
            ]
              .filter(Boolean)
              .join(' ')}
          >
            {children}
          </div>
        ) : (
          <div className={contentClassName}>{children}</div>
        )}

        {(primaryAction || secondaryAction) ? (
          <div className="mt-10 flex flex-col gap-4 sm:flex-row">
            {primaryAction ? (
              <CtaLink
                href={primaryAction.href}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-7 py-3.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_24px_rgba(6,182,212,0.35)]"
              >
                {primaryAction.label}
                {primaryAction.icon || <ArrowRight className="h-4 w-4" />}
              </CtaLink>
            ) : null}

            {secondaryAction ? (
              <CtaLink
                href={secondaryAction.href}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-200/60 bg-white px-7 py-3.5 text-sm font-semibold text-zinc-800 shadow-[0_0_15px_rgba(6,182,212,0.08)] transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-400 hover:bg-cyan-50/40 hover:shadow-[0_0_20px_rgba(6,182,212,0.18)]"
              >
                {secondaryAction.label}
                {secondaryAction.icon || <ExternalLink className="h-4 w-4 text-cyan-600" />}
              </CtaLink>
            ) : null}
          </div>
        ) : null}
      </main>
    </div>
  );
}

function PolicyPage({ title, sections }) {
  return (
    <PageShell
      eyebrow="Maestro Fleet"
      title={title}
      primaryAction={{ href: '/', label: 'Back to home' }}
    >
      <div className="space-y-8">
        {sections.map((section) => (
          <section key={section.heading}>
            <h2 className="mb-3 text-xl font-bold tracking-tight text-zinc-950">{section.heading}</h2>
            <div className="space-y-3 text-sm leading-7 text-zinc-800">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
          </section>
        ))}
      </div>
    </PageShell>
  );
}

function CheckoutStatusPage({ type, primaryContactHref }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(type === 'success');
  const [error, setError] = useState('');

  useEffect(() => {
    if (type !== 'success' || typeof window === 'undefined') {
      return undefined;
    }

    const searchParams = new URLSearchParams(window.location.search);
    const sessionId = searchParams.get('session_id');

    if (!sessionId) {
      setLoading(false);
      return undefined;
    }

    let cancelled = false;

    const loadSummary = async () => {
      try {
        const response = await fetch(`/api/stripe/session?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) {
          throw new Error('Unable to load checkout confirmation details.');
        }

        const data = await response.json();
        if (!cancelled) {
          setSummary(data);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Unable to load checkout details.');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadSummary();

    return () => {
      cancelled = true;
    };
  }, [type]);

  const isSuccess = type === 'success';
  const title = isSuccess ? 'Checkout complete.' : 'Checkout canceled.';
  const intro = isSuccess
    ? 'Your payment went through. If this was a setup purchase, the next step is scheduling or confirming your deployment session. If this was monthly coverage, your customer record has been synced into operations automation.'
    : 'No payment was completed. You can return to the pricing section, review the offer, or book a consultation if you want to talk through the fit first.';

  return (
    <PageShell
      eyebrow={isSuccess ? 'Payment Complete' : 'Checkout Interrupted'}
      title={title}
      intro={intro}
      primaryAction={{ href: isSuccess ? primaryContactHref || '/' : '/#get-started', label: isSuccess ? 'Schedule next step' : 'Return to pricing' }}
      secondaryAction={{ href: '/', label: 'Back to home' }}
    >
      <div className="space-y-6">
        {loading ? <p className="text-sm text-zinc-500">Loading checkout details...</p> : null}
        {error ? <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{error}</p> : null}

        {summary ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="mb-1 text-xs font-bold uppercase tracking-widest text-zinc-400">Purchase Type</div>
              <div className="text-lg font-semibold text-zinc-950">
                {summary.purchaseType === 'setup'
                  ? 'Fleet setup'
                  : summary.purchaseType === 'monthly'
                    ? 'Monthly coverage'
                    : 'General checkout'}
              </div>
            </div>
            <div className="rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="mb-1 text-xs font-bold uppercase tracking-widest text-zinc-400">Amount</div>
              <div className="text-lg font-semibold text-zinc-950">{summary.amountTotalFormatted || 'Paid'}</div>
            </div>
            <div className="rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="mb-1 text-xs font-bold uppercase tracking-widest text-zinc-400">Customer</div>
              <div className="text-sm font-medium text-zinc-800">{summary.customerName || summary.customerEmail || 'Confirmed'}</div>
            </div>
            <div className="rounded-2xl border border-zinc-200 bg-white p-5">
              <div className="mb-1 text-xs font-bold uppercase tracking-widest text-zinc-400">Status</div>
              <div className="text-sm font-medium uppercase tracking-wide text-emerald-700">{summary.paymentStatus || 'complete'}</div>
            </div>
          </div>
        ) : null}

        <div className="rounded-2xl border border-cyan-200/60 bg-cyan-50/60 p-5 text-sm leading-7 text-zinc-800">
          <p>
            The production flow now supports a branded confirmation path plus Stripe to Kit automation through the
            Vercel webhook endpoint. If you bought monthly coverage, future subscription changes are also tracked on the
            operations side.
          </p>
        </div>
      </div>
    </PageShell>
  );
}

function buildPolicyContent(contactEmail) {
  const contactLine = contactEmail
    ? `You can reach us at ${contactEmail}.`
    : '';
  return {
    privacy: [
      {
        heading: 'Information we collect',
        paragraphs: [
          'We collect information you provide through the website, scheduling links, payment forms, and email signup forms. That may include your name, company, email address, phone number, and any project information you choose to share during a consultation or onboarding process.',
          'We also receive operational data from service providers that support the website and customer workflow, including Vercel for hosting, Calendly for scheduling, Stripe for payments, and Kit for email marketing and lifecycle communication.',
        ],
      },
      {
        heading: 'How we use it',
        paragraphs: [
          'We use your information to respond to inquiries, schedule consultations, process payments, deliver services, provide support, and send product or marketing communications relevant to Maestro Fleet.',
          'If you join our email list, you can unsubscribe at any time using the links in those emails.',
        ],
      },
      {
        heading: 'Data handling',
        paragraphs: [
          'We do not sell your personal information. We share data only with vendors required to operate the service and only to the extent needed to host the website, process payments, send email, or provide scheduling and support.',
          `If you have questions about your data or want information updated or removed, contact us directly by email.${contactLine ? ` ${contactLine}` : ''}`,
        ],
      },
    ],
    terms: [
      {
        heading: 'Scope of service',
        paragraphs: [
          'Maestro Fleet deployment and support services are provided as a business-to-business offering. Final implementation scope, support terms, and operating expectations are confirmed during the consultation and onboarding process.',
          'Any timelines or deployment statements on the website describe the standard operating target, not a legally guaranteed delivery deadline for every project configuration.',
        ],
      },
      {
        heading: 'Use of the website',
        paragraphs: [
          'You agree not to misuse the website, interfere with service providers that support it, or attempt unauthorized access to systems, accounts, payment flows, or infrastructure.',
          'All website content, branding, and product descriptions remain the property of Maestro Systems unless otherwise stated.',
        ],
      },
      {
        heading: 'Commercial terms',
        paragraphs: [
          'Commercial terms are finalized during consultation and onboarding. Invoices are issued after scope confirmation using the billing platform selected for the engagement, such as Stripe Invoicing or QuickBooks.',
          'To the maximum extent permitted by law, liability is limited to amounts paid for the applicable service period unless a separate written agreement states otherwise.',
        ],
      },
    ],
    refund: [
      {
        heading: 'Setup payments',
        paragraphs: [
          'Setup purchases reserve deployment time and preparation effort. If you need to cancel after purchase, contact us as soon as possible. Refund decisions for setup work are handled case by case based on work already performed, preparation already completed, and time already reserved.',
        ],
      },
      {
        heading: 'Monthly coverage',
        paragraphs: [
          'Monthly support and maintenance charges can be canceled prospectively. Charges already incurred for an active service period are generally non-refundable unless required by law or otherwise agreed in writing.',
        ],
      },
      {
        heading: 'How to request help',
        paragraphs: [
          `For billing questions, cancellation requests, or refund discussions, reach out directly so we can review the specific account and timeline involved.${contactLine ? ` ${contactLine}` : ''}`,
        ],
      },
    ],
  };
}

function BuiltForPage({ primaryContactHref }) {
  const contractorTypes = [
    {
      icon: Building2,
      title: 'General Contractors',
      description:
        'You are coordinating every discipline on the job. Maestro reads every sheet in the set, answers questions across trades, and gives you a command layer across your entire portfolio. One agent per project, one Commander for the operation.',
    },
    {
      icon: Flame,
      title: 'Mechanical, Electrical & Plumbing',
      description:
        'Your scope lives in the mechanical, electrical, and plumbing sheets but touches every other discipline on the project. Maestro isolates your drawings, understands your specs, and answers coordination questions against the full set.',
    },
    {
      icon: Mountain,
      title: 'Civil & Site Contractors',
      description:
        'Grading plans, utility layouts, stormwater details, paving specs. Maestro reads civil drawings the same way it reads architectural or structural. Your field team asks questions and gets answers from the plans in seconds.',
    },
    {
      icon: Hammer,
      title: 'Specialty Contractors',
      description:
        'Steel, concrete, fire protection, roofing, finish carpentry, landscaping. If you build from drawings, Maestro works for you. It ingests your plan set, learns your scope, and gives your crew a way to get answers without calling the office.',
    },
  ];

  const roles = [
    {
      icon: MessageSquare,
      label: 'From the field',
      labelColor: 'text-cyan-600',
      iconColor: 'text-cyan-600',
      title: 'Your field team stops waiting for answers.',
      description:
        'Foremen, superintendents, and crew leads text the project agent from the jobsite and get answers from the plans in seconds. Specs, details, scope clarifications, schedule questions. No phone calls. No flipping through binders. No waiting for someone in the office to look it up.',
      items: [
        'Ask about any detail on any sheet from the field',
        'Get visual workspaces with annotated plan pages',
        'Talk through the schedule in natural conversation',
        'Works from the truck, the trailer, or the slab',
      ],
      checkColor: 'text-cyan-500 drop-shadow-[0_0_3px_rgba(6,182,212,0.4)]',
      borderColor: 'border-cyan-100/80',
      glowColor: 'bg-cyan-400/10',
      hoverShadow: 'hover:shadow-[0_10px_30px_-15px_rgba(6,182,212,0.2)]',
    },
    {
      icon: Network,
      label: 'From the office',
      labelColor: 'text-zinc-500',
      iconColor: 'text-zinc-700',
      title: 'Your office sees everything without the phone calls.',
      description:
        'Project managers, estimators, principals, and owners open the Command Center and see every project in the fleet. Ask the Commander which jobs need attention, compare schedule health across projects, or get a cross-project risk summary. No status meetings required.',
      items: [
        'Portfolio-level visibility across all active projects',
        'Cross-project intelligence and risk surfacing',
        'Create new project agents when you win work',
        'One command layer for the whole operation',
      ],
      checkColor: 'text-zinc-300',
      borderColor: 'border-zinc-200/80',
      glowColor: 'bg-cyan-500/5',
      hoverShadow: 'hover:shadow-[0_10px_30px_-15px_rgba(6,182,212,0.1)]',
    },
  ];

  return (
    <div className="min-h-screen bg-white text-zinc-800 antialiased selection:bg-cyan-100 selection:text-cyan-900">
      <div className="border-b border-zinc-200/70 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <a href="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-950 shadow-[0_0_15px_rgba(6,182,212,0.3)]">
              <span className="font-mono text-xs font-bold tracking-wider text-cyan-400">MF</span>
            </div>
            <span className="font-semibold tracking-tight text-zinc-950">Maestro Fleet</span>
          </a>
          <FooterLinks />
        </div>
      </div>

      <main className="mx-auto max-w-6xl px-6 py-20 md:py-28">
        <div className="mx-auto max-w-3xl text-center">
          <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.3)]">
            Who It&apos;s For
          </p>
          <h1 className="mb-6 text-4xl font-bold leading-tight tracking-tight text-zinc-950 md:text-5xl">
            Built for contractors who build from plans.
          </h1>
          <p className="mb-6 text-lg leading-relaxed text-zinc-700">
            If your team reads drawings and builds from them, Maestro Fleet works for you. General contractors, mechanical
            contractors, electrical contractors, plumbers, civil contractors, specialty subs. Any contractor running
            projects off plan sets.
          </p>
          <p className="text-zinc-500">
            The system is the same. A dedicated AI agent on every project that reads your plans, answers questions from
            the field, and tracks your schedule. A command layer that gives your office visibility across every job.
          </p>
        </div>

        <div className="mt-20 grid gap-6 md:grid-cols-2">
          {contractorTypes.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="group relative overflow-hidden rounded-2xl border border-zinc-200/80 bg-white p-8 transition-all duration-500 hover:-translate-y-1 hover:shadow-[0_20px_40px_-15px_rgba(6,182,212,0.15)]"
            >
              <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/0 to-cyan-500/0 transition-colors duration-500 group-hover:to-cyan-500/5" />
              <div className="relative">
                <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-100 bg-cyan-50/80 transition-all duration-500 group-hover:border-cyan-400 group-hover:bg-cyan-500 group-hover:shadow-[0_0_20px_rgba(6,182,212,0.4)]">
                  <Icon className="h-5 w-5 text-cyan-600 transition-colors duration-500 group-hover:text-white" />
                </div>
                <h3 className="mb-3 text-xl font-bold tracking-tight text-zinc-950">{title}</h3>
                <p className="text-sm leading-relaxed text-zinc-700">{description}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-24">
          <div className="mx-auto mb-16 max-w-2xl text-center">
            <h2 className="mb-4 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
              Two sides of the same system.
            </h2>
            <p className="text-lg leading-relaxed text-zinc-700">
              Maestro Fleet connects the field and the office through a single intelligence layer. Your field crew gets
              answers. Your office gets visibility. Nobody waits.
            </p>
          </div>

          <div className="grid gap-8 lg:grid-cols-2">
            {roles.map(({ icon: Icon, label, labelColor, iconColor, title, description, items, checkColor, borderColor, glowColor, hoverShadow }) => (
              <div
                key={label}
                className={`relative overflow-hidden rounded-2xl border ${borderColor} bg-white p-10 shadow-[0_10px_30px_-15px_rgba(0,0,0,0.05)] transition-shadow ${hoverShadow}`}
              >
                <div className={`absolute -right-10 -top-10 h-40 w-40 rounded-full ${glowColor} blur-[50px]`} />
                <div className="relative">
                  <div className="mb-6 flex items-center gap-2.5">
                    <Icon className={`h-5 w-5 ${iconColor}`} />
                    <span className={`text-[11px] font-bold uppercase tracking-widest ${labelColor}`}>{label}</span>
                  </div>
                  <h3 className="mb-4 text-2xl font-bold tracking-tight text-zinc-950">{title}</h3>
                  <p className="mb-8 leading-relaxed text-zinc-700">{description}</p>
                  <div className="space-y-3">
                    {items.map((item) => (
                      <div key={item} className="flex items-start gap-3 text-sm font-medium text-zinc-800">
                        <CheckCircle2 className={`mt-0.5 h-4 w-4 shrink-0 ${checkColor}`} />
                        <span>{item}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-20 text-center">
          <CtaLink
            href={primaryContactHref}
            className="group inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-10 py-4 text-base font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_30px_rgba(6,182,212,0.4)]"
          >
            <Calendar className="h-4 w-4 text-cyan-400" />
            Book a Consultation
            <ArrowUpRight className="h-4 w-4 text-cyan-400 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
          </CtaLink>
          <p className="mt-5 text-sm font-medium text-zinc-400">
            We will walk through your operation and show you how the fleet maps to your projects.
          </p>
        </div>

        <div className="mt-10 flex justify-center">
          <a
            href="/"
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-200/60 bg-white px-7 py-3.5 text-sm font-semibold text-zinc-800 shadow-[0_0_15px_rgba(6,182,212,0.08)] transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-400 hover:bg-cyan-50/40 hover:shadow-[0_0_20px_rgba(6,182,212,0.18)]"
          >
            Back to home
            <ArrowRight className="h-4 w-4" />
          </a>
        </div>
      </main>
    </div>
  );
}

function SchedulePage({ calendlyUrl, contactEmail }) {
  const embedRef = useRef(null);
  const processedBookingKeysRef = useRef(new Set());
  const [embedStatus, setEmbedStatus] = useState(calendlyUrl ? 'loading' : 'missing');
  const [syncStatus, setSyncStatus] = useState('idle');
  const [syncMessage, setSyncMessage] = useState('');

  useEffect(() => {
    if (!calendlyUrl || typeof window === 'undefined' || !embedRef.current) {
      return undefined;
    }

    let cancelled = false;
    setEmbedStatus('loading');

    loadCalendlyScript()
      .then((Calendly) => {
        if (cancelled || !embedRef.current || !Calendly?.initInlineWidget) {
          return;
        }

        embedRef.current.innerHTML = '';
        Calendly.initInlineWidget({
          url: calendlyUrl,
          parentElement: embedRef.current,
        });

        // Once the Calendly iframe loads, force it to fill the container
        const observer = new MutationObserver(() => {
          const iframe = embedRef.current?.querySelector('iframe');
          if (iframe) {
            iframe.style.height = '100%';
            iframe.style.minHeight = '100%';
          }
        });
        observer.observe(embedRef.current, { childList: true, subtree: true });

        setEmbedStatus('ready');

        return () => observer.disconnect();
      })
      .catch(() => {
        if (!cancelled) {
          setEmbedStatus('error');
        }
      });

    return () => {
      cancelled = true;
      if (embedRef.current) {
        embedRef.current.innerHTML = '';
      }
    };
  }, [calendlyUrl]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }

    const handleMessage = async (event) => {
      if (event.origin !== 'https://calendly.com' || event.data?.event !== 'calendly.event_scheduled') {
        return;
      }

      const payload = event.data?.payload && typeof event.data.payload === 'object' ? event.data.payload : {};
      const bookingKey = payload?.invitee?.uri || payload?.event?.uri || JSON.stringify(payload);
      const sessionStorageKey = bookingKey ? `calendly-booking:${bookingKey}` : '';

      if (processedBookingKeysRef.current.has(bookingKey)) {
        return;
      }

      if (sessionStorageKey && window.sessionStorage.getItem(sessionStorageKey) === 'done') {
        processedBookingKeysRef.current.add(bookingKey);
        setSyncStatus('success');
        setSyncMessage('Booked. Your email is already synced for follow-up.');
        return;
      }

      processedBookingKeysRef.current.add(bookingKey);
      if (sessionStorageKey) {
        window.sessionStorage.setItem(sessionStorageKey, 'pending');
      }

      setSyncStatus('syncing');
      setSyncMessage('');

      try {
        const response = await fetch('/api/calendly/booked', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ payload }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || 'Unable to sync booking details.');
        }

        setSyncStatus('success');
        setSyncMessage('Booked. Your email has been added for Maestro follow-up.');
        if (sessionStorageKey) {
          window.sessionStorage.setItem(sessionStorageKey, 'done');
        }
      } catch (error) {
        if (sessionStorageKey) {
          window.sessionStorage.removeItem(sessionStorageKey);
        }
        processedBookingKeysRef.current.delete(bookingKey);
        setSyncStatus('error');
        setSyncMessage(error instanceof Error ? error.message : 'Your booking went through, but we could not sync email automatically.');
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  return (
    <div className="flex min-h-[100svh] flex-col bg-white text-zinc-800 antialiased selection:bg-cyan-100 selection:text-cyan-900">
      <div className="border-b border-zinc-200/70 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <a href="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-950 shadow-[0_0_15px_rgba(6,182,212,0.3)]">
              <span className="font-mono text-xs font-bold tracking-wider text-cyan-400">MF</span>
            </div>
            <span className="font-semibold tracking-tight text-zinc-950">Maestro Fleet</span>
          </a>
          <FooterLinks />
        </div>
      </div>

      <div className="mx-auto w-full max-w-5xl px-4 pt-10 sm:px-6 md:pt-16">
        <div className="max-w-3xl">
          <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.25)]">
            Book a Consultation
          </p>
          <h1 className="mb-4 text-3xl font-bold leading-tight tracking-tight text-zinc-950 sm:text-4xl md:text-5xl">
            Pick a time that works.
          </h1>
          <p className="mb-6 text-base leading-relaxed text-zinc-700 sm:text-lg">
            We&apos;ll walk through your operation and show you how the fleet maps to your projects.
          </p>
        </div>

        {syncStatus === 'syncing' ? (
          <p className="mb-4 text-sm font-semibold text-cyan-700">Booking confirmed. Syncing your email now…</p>
        ) : null}
        {syncStatus === 'success' ? (
          <p className="mb-4 text-sm font-semibold text-emerald-700">{syncMessage}</p>
        ) : null}
        {syncStatus === 'error' ? (
          <p className="mb-4 text-sm font-semibold text-amber-700">{syncMessage}</p>
        ) : null}
      </div>

      {embedStatus === 'missing' ? (
        <div className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6">
          <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-sm text-zinc-700 sm:p-8">
            Scheduling is not configured yet.{' '}
            {contactEmail ? (
              <>
                <a href={`mailto:${contactEmail}`} className="font-semibold text-cyan-600 underline hover:text-cyan-700">
                  Email us
                </a>{' '}
                and we&apos;ll coordinate directly.
              </>
            ) : (
              'Check back soon.'
            )}
          </div>
        </div>
      ) : null}

      {embedStatus === 'error' ? (
        <div className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6">
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900 sm:p-8">
            The scheduler could not load.{' '}
            {calendlyUrl ? (
              <a href={calendlyUrl} target="_blank" rel="noreferrer" className="font-semibold underline">
                Open Calendly directly
              </a>
            ) : null}
          </div>
        </div>
      ) : null}

      {calendlyUrl ? (
        <div className="flex-1">
          <div
            ref={embedRef}
            className="mx-auto h-full min-h-[calc(100svh-4rem)] w-full max-w-5xl"
          />
        </div>
      ) : null}

      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 py-8 sm:flex-row sm:px-6">
        {calendlyUrl ? (
          <a
            href={calendlyUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-7 py-3.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_24px_rgba(6,182,212,0.35)]"
          >
            Open in new tab
            <ExternalLink className="h-4 w-4" />
          </a>
        ) : null}
        {contactEmail ? (
          <a
            href={`mailto:${contactEmail}`}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-200/60 bg-white px-7 py-3.5 text-sm font-semibold text-zinc-800 shadow-[0_0_15px_rgba(6,182,212,0.08)] transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-400 hover:bg-cyan-50/40 hover:shadow-[0_0_20px_rgba(6,182,212,0.18)]"
          >
            Email instead
            <ExternalLink className="h-4 w-4 text-cyan-600" />
          </a>
        ) : null}
        <a
          href="/"
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-200 bg-white px-7 py-3.5 text-sm font-semibold text-zinc-600 transition-all duration-300 hover:-translate-y-0.5 hover:border-zinc-300 hover:text-zinc-800"
        >
          Back to home
          <ArrowRight className="h-4 w-4" />
        </a>
      </div>
    </div>
  );
}

function renderStandalonePage(pathname, primaryContactHref, contactEmail, calendlyUrl) {
  const content = buildPolicyContent(contactEmail);

  if (pathname === '/privacy') {
    return <PolicyPage title="Privacy Policy" sections={content.privacy} />;
  }

  if (pathname === '/terms') {
    return <PolicyPage title="Terms of Service" sections={content.terms} />;
  }

  if (pathname === '/refund') {
    return <PolicyPage title="Refund Policy" sections={content.refund} />;
  }

  if (pathname === '/built-for') {
    return <BuiltForPage primaryContactHref={primaryContactHref} />;
  }

  if (pathname === '/schedule') {
    return <SchedulePage calendlyUrl={calendlyUrl} contactEmail={contactEmail} />;
  }

  if (pathname === '/checkout/success') {
    return <CheckoutStatusPage type="success" primaryContactHref={primaryContactHref} />;
  }

  if (pathname === '/checkout/cancel') {
    return <CheckoutStatusPage type="cancel" primaryContactHref={primaryContactHref} />;
  }

  return null;
}

export default function App() {
  const calendlyUrl = cleanText(import.meta.env.VITE_CALENDLY_URL);
  const setupPriceLabel = cleanText(import.meta.env.VITE_STRIPE_SETUP_PRICE_LABEL) || '$1,500';
  const monthlyPriceLabel = cleanText(import.meta.env.VITE_STRIPE_MONTHLY_PRICE_LABEL) || '$400 / month';
  const contactEmail = cleanText(import.meta.env.VITE_CONTACT_EMAIL);
  const primaryContactHref = calendlyUrl ? '/schedule' : (contactEmail ? `mailto:${contactEmail}` : '');
  const pathname = typeof window !== 'undefined' ? window.location.pathname : '/';

  useEffect(() => {
    if (typeof document === 'undefined') {
      return;
    }

    const titles = {
      '/': 'Maestro Fleet | Construction Intelligence Operating System',
      '/privacy': 'Maestro Fleet | Privacy Policy',
      '/terms': 'Maestro Fleet | Terms of Service',
      '/refund': 'Maestro Fleet | Refund Policy',
      '/built-for': 'Maestro Fleet | Built for Contractors',
      '/schedule': 'Maestro Fleet | Book a Consultation',
      '/checkout/success': 'Maestro Fleet | Checkout Complete',
      '/checkout/cancel': 'Maestro Fleet | Checkout Canceled',
    };

    document.title = titles[pathname] || titles['/'];
  }, [pathname]);

  const standalonePage = renderStandalonePage(pathname, primaryContactHref, contactEmail, calendlyUrl);
  if (standalonePage) {
    return standalonePage;
  }

  return (
    <div className="min-h-screen bg-white font-sans text-zinc-800 antialiased selection:bg-cyan-100 selection:text-cyan-900">
      <MobileNav primaryContactHref={primaryContactHref} />

      <section className="relative overflow-hidden bg-white">
        <div
          className="absolute inset-0 opacity-[0.25]"
          style={{
            backgroundImage:
              'linear-gradient(#a5f3fc 1px, transparent 1px), linear-gradient(90deg, #a5f3fc 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />
        <div className="pointer-events-none absolute left-1/2 top-[-10%] h-[600px] w-[800px] -translate-x-1/2 rounded-full bg-cyan-400/15 blur-[120px]" />

        <div className="relative mx-auto max-w-6xl px-6 pb-24 pt-28 md:pb-36 md:pt-40">
          <div className="max-w-3xl">
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-cyan-200/80 bg-white/80 px-3.5 py-1.5 text-sm font-medium text-zinc-700 shadow-[0_0_15px_rgba(6,182,212,0.15)] backdrop-blur-md">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
              Construction Intelligence Operating System
            </div>

            <h1 className="mb-8 text-5xl font-extrabold leading-[1.05] tracking-tighter text-zinc-950 md:text-[4.5rem]">
              Your plans finally
              <br />
              talk back.
            </h1>

            <p className="mb-6 max-w-2xl text-xl font-light leading-relaxed tracking-tight text-zinc-700 md:text-2xl">
              You already know what needs to get built. Maestro Fleet is the operating system that makes sure nothing
              gets missed, nobody waits for answers, and every job has intelligence that keeps up with the pace of the
              work.
            </p>

            <p className="mb-12 max-w-xl text-lg leading-relaxed text-zinc-500">
              AI agents that live on your projects, read your plans, and answer questions from the field. A command
              layer that gives your office visibility across every job you&apos;re running.
            </p>

            <div className="flex flex-col gap-4 sm:flex-row">
              <CtaLink
                href={primaryContactHref}
                className="group inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-8 py-4 text-base font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_25px_rgba(6,182,212,0.4)]"
              >
                <Calendar className="h-4 w-4 text-cyan-400" />
                Book a Consultation
                <ArrowUpRight className="h-4 w-4 text-cyan-400 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </CtaLink>

              <CtaLink
                href="#how-it-works"
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-200/50 bg-white px-8 py-4 text-base font-semibold text-zinc-700 shadow-[0_0_15px_rgba(6,182,212,0.05)] transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-400 hover:bg-cyan-50/30 hover:shadow-[0_0_20px_rgba(6,182,212,0.15)]"
              >
                See How It Works
              </CtaLink>
            </div>
          </div>

          <div className="mt-20 grid max-w-2xl grid-cols-3 gap-8 border-t border-zinc-100 pt-10 md:mt-28">
            <div>
              <div className="text-3xl font-extrabold tracking-tight text-zinc-950 tabular-nums md:text-4xl">100%</div>
              <div className="mt-1 text-sm font-medium uppercase tracking-wide text-zinc-400">On your hardware</div>
            </div>
            <div>
              <div className="text-3xl font-extrabold tracking-tight text-zinc-950 tabular-nums md:text-4xl">&lt; 30s</div>
              <div className="mt-1 text-sm font-medium uppercase tracking-wide text-zinc-400">Plan answers</div>
            </div>
            <div>
              <div className="text-3xl font-extrabold tracking-tight text-zinc-950 tabular-nums md:text-4xl">&infin;</div>
              <div className="mt-1 text-sm font-medium uppercase tracking-wide text-zinc-400">Projects per fleet</div>
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="border-t border-zinc-200 bg-zinc-50/50">
        <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="mb-16 max-w-2xl">
            <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.3)]">
              How It Works
            </p>
            <h2 className="mb-5 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
              Ask a question. See the answer on the plans. Build the schedule. Move on.
            </h2>
            <p className="text-lg leading-relaxed text-zinc-700">
              Your people shouldn&apos;t have to dig through 500 pages of drawings to find the detail that matters right
              now. Maestro reads every sheet, understands the relationships between them, and gives your field team a
              way to get answers as fast as they can ask.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                icon: Search,
                step: 'Step 01',
                title: 'Ask about anything on the job.',
                copy:
                  'Walk-in cooler specs. Foundation pour sequencing. Fire protection layout. Ansul system details. Ask your project agent and it searches every sheet across every discipline. Answers come back in seconds with the details cited.',
              },
              {
                icon: Layers,
                step: 'Step 02',
                title: 'See it on the plans. Visually.',
                copy:
                  'Tell Maestro to build a workspace and it pulls every relevant page, highlights the specs that matter, and adds notes that explain how the details connect across sheets. Not a text summary, the actual drawings, annotated and ready to hand to your foreman.',
              },
              {
                icon: CalendarClock,
                step: 'Step 03',
                title: 'Talk through the plan of attack.',
                copy:
                  'Hash out the schedule in conversation. What needs to happen first, who you need on site, when you want to hit the milestone. Maestro captures it all, activities, sequencing, dependencies, and commits it to the project schedule instantly.',
              },
            ].map(({ icon: Icon, step, title, copy }) => (
              <div
                key={step}
                className="group relative overflow-hidden rounded-2xl border border-zinc-200/80 bg-white p-8 transition-all duration-500 hover:-translate-y-1.5 hover:shadow-[0_20px_40px_-15px_rgba(6,182,212,0.2)]"
              >
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/0 to-cyan-500/0 transition-colors duration-500 group-hover:to-cyan-500/5" />
                <div className="relative">
                  <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-100 bg-cyan-50/80 transition-all duration-500 group-hover:border-cyan-400 group-hover:bg-cyan-500 group-hover:shadow-[0_0_20px_rgba(6,182,212,0.4)]">
                    <Icon className="h-5 w-5 text-cyan-600 transition-colors duration-500 group-hover:text-white" />
                  </div>
                  <div className="mb-4 font-mono text-[11px] font-bold uppercase tracking-widest text-zinc-400">{step}</div>
                  <h3 className="mb-3 text-xl font-bold tracking-tight text-zinc-950 transition-colors group-hover:text-cyan-900">
                    {title}
                  </h3>
                  <p className="text-sm leading-relaxed text-zinc-700">{copy}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-16 max-w-2xl border-l-2 border-cyan-200 pl-6">
            <p className="text-lg italic leading-relaxed text-zinc-600">
              This works for any concept your field team needs to work through. Foundation pours. Fryer hoods.
              Mechanical rough-in. Steel erection. Landscaping. Finish carpentry. Whatever the day demands.
            </p>
          </div>
        </div>
      </section>

      <section id="the-fleet" className="border-t border-zinc-200">
        <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="mb-16 max-w-2xl">
            <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.3)]">
              The Fleet
            </p>
            <h2 className="mb-5 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
              That&apos;s one project.
              <br />
              Now picture every job you&apos;re running.
            </h2>
            <p className="text-lg leading-relaxed text-zinc-700">
              Maestro Fleet puts a dedicated agent on every project in your portfolio and connects them all to a
              command layer your office can see. Each agent is isolated to its own job, own plans, own schedule, own
              conversations. The command layer sees across all of them.
            </p>
          </div>

          <div className="mx-auto mb-20 max-w-4xl">
            <div className="relative overflow-hidden rounded-3xl border border-cyan-900/50 bg-zinc-950 p-8 shadow-[0_20px_50px_-15px_rgba(6,182,212,0.3)] md:p-12">
              <div
                className="absolute inset-0 opacity-[0.2]"
                style={{
                  backgroundImage:
                    'linear-gradient(#0891b2 1px, transparent 1px), linear-gradient(90deg, #0891b2 1px, transparent 1px)',
                  backgroundSize: '40px 40px',
                }}
              />
              <div className="pointer-events-none absolute left-1/2 top-0 h-[300px] w-full -translate-x-1/2 bg-cyan-500/15 blur-[80px]" />

              <div className="relative">
                <div className="mb-8 flex justify-center">
                  <div className="rounded-2xl border border-cyan-400/50 bg-zinc-950/80 px-8 py-5 text-center shadow-[0_0_20px_rgba(6,182,212,0.2),0_0_0_1px_rgba(6,182,212,0.1)_inset] backdrop-blur-md">
                    <div className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-cyan-400 drop-shadow-[0_0_5px_rgba(34,211,238,0.8)]">
                      Command Layer
                    </div>
                    <div className="text-lg font-bold tracking-tight text-white">The Commander</div>
                    <div className="mt-2 text-xs font-medium text-cyan-100/60">Portfolio visibility · Routing · Health</div>
                  </div>
                </div>

                <div className="mb-8 flex justify-center">
                  <svg width="420" height="40" viewBox="0 0 420 40" className="max-w-full text-cyan-500/60 drop-shadow-[0_0_8px_rgba(6,182,212,0.5)]">
                    <line x1="210" y1="0" x2="210" y2="14" stroke="currentColor" strokeWidth="2" />
                    <line x1="70" y1="14" x2="350" y2="14" stroke="currentColor" strokeWidth="2" />
                    <line x1="70" y1="14" x2="70" y2="40" stroke="currentColor" strokeWidth="2" />
                    <line x1="210" y1="14" x2="210" y2="40" stroke="currentColor" strokeWidth="2" />
                    <line x1="350" y1="14" x2="350" y2="40" stroke="currentColor" strokeWidth="2" />
                  </svg>
                </div>

                <div className="mx-auto grid max-w-lg grid-cols-3 gap-4 md:gap-6">
                  {['Riverside Tower', 'Highway 101', 'Market Square'].map((name) => (
                    <div
                      key={name}
                      className="rounded-xl border border-cyan-800/40 bg-zinc-900/60 p-4 text-center backdrop-blur transition-all hover:border-cyan-500/60 hover:bg-zinc-800 hover:shadow-[0_0_20px_rgba(6,182,212,0.2)]"
                    >
                      <div className="mb-3 flex justify-center">
                        <div className="h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.8)]" />
                      </div>
                      <div className="text-sm font-semibold tracking-tight text-white">{name}</div>
                      <div className="mt-1.5 font-mono text-[10px] uppercase tracking-widest text-cyan-200/50">Isolated</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                icon: Crosshair,
                title: 'Project Isolation',
                copy:
                  'Every job gets its own agent, its own workspace, its own plan store, its own schedule. No context bleeds across projects. Your people talk to the agent that knows their job and only their job.',
              },
              {
                icon: Eye,
                title: 'Portfolio Visibility',
                copy:
                  'The Commander queries every project agent and surfaces what matters. Which jobs need attention. Where risk is concentrated. What is behind schedule. One command layer for the whole operation.',
              },
              {
                icon: Wrench,
                title: 'Operational Control',
                copy:
                  'Fleet is not a dashboard you look at. It is a system you run. Create project agents. Ingest plan sets. Monitor health. Repair issues. Route questions to the right level. It governs the fleet.',
              },
            ].map(({ icon: Icon, title, copy }) => (
              <div key={title} className="rounded-2xl border border-zinc-200/60 bg-zinc-50 p-8">
                <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-lg border border-zinc-200 bg-white shadow-sm">
                  <Icon className="h-5 w-5 text-zinc-700" />
                </div>
                <h3 className="mb-2 text-lg font-bold text-zinc-950">{title}</h3>
                <p className="text-sm leading-relaxed text-zinc-700">{copy}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t border-zinc-200 bg-zinc-50">
        <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="grid gap-8 lg:grid-cols-2">
            <div className="relative overflow-hidden rounded-2xl border border-cyan-100/80 bg-white p-10 shadow-[0_10px_30px_-15px_rgba(6,182,212,0.1)] transition-shadow hover:shadow-[0_10px_30px_-15px_rgba(6,182,212,0.2)]">
              <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-cyan-400/10 blur-[50px]" />
              <div className="relative">
                <div className="mb-6 flex items-center gap-2.5">
                  <MessageSquare className="h-5 w-5 text-cyan-600" />
                  <span className="text-[11px] font-bold uppercase tracking-widest text-cyan-600">From the field</span>
                </div>
                <h3 className="mb-4 text-2xl font-bold tracking-tight text-zinc-950">A dedicated brain for every jobsite.</h3>
                <p className="mb-8 leading-relaxed text-zinc-700">
                  Your foremen and supers get a project agent that knows their job. They text it from the field and get
                  answers from the plans in seconds. It tracks the schedule. It builds visual workspaces. It is always
                  available, and it never forgets what is in the drawings.
                </p>
                <div className="space-y-3">
                  {[
                    'Text questions about specs, details, or scope from anywhere',
                    'Visual workspaces with annotated plan sheets',
                    'Schedule management through natural conversation',
                    'Isolated to one project, no cross-job confusion',
                  ].map((item) => (
                    <div key={item} className="flex items-start gap-3 text-sm font-medium text-zinc-800">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-cyan-500 drop-shadow-[0_0_3px_rgba(6,182,212,0.4)]" />
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="relative overflow-hidden rounded-2xl border border-zinc-200/80 bg-white p-10 shadow-[0_10px_30px_-15px_rgba(0,0,0,0.05)] transition-shadow hover:shadow-[0_10px_30px_-15px_rgba(6,182,212,0.1)]">
              <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-cyan-500/5 blur-[50px]" />
              <div className="relative">
                <div className="mb-6 flex items-center gap-2.5">
                  <Network className="h-5 w-5 text-zinc-700" />
                  <span className="text-[11px] font-bold uppercase tracking-widest text-zinc-500">From the office</span>
                </div>
                <h3 className="mb-4 text-2xl font-bold tracking-tight text-zinc-950">The whole operation. One screen.</h3>
                <p className="mb-8 leading-relaxed text-zinc-700">
                  Open the Command Center and see every project in the fleet. Ask the Commander which jobs need
                  attention, compare schedule health, or get a cross-project risk summary. Create new project agents
                  when you win work. The command layer keeps leadership connected without the phone calls.
                </p>
                <div className="space-y-3">
                  {[
                    'Portfolio-level visibility across all projects',
                    'Cross-project intelligence and risk surfacing',
                    'Fleet health monitoring and self-repair',
                    'Provision and govern project agents from one place',
                  ].map((item) => (
                    <div key={item} className="flex items-start gap-3 text-sm font-medium text-zinc-800">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-zinc-300" />
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-12 text-center">
            <a
              href="/built-for"
              className="group inline-flex items-center gap-2 text-sm font-semibold text-cyan-600 transition-colors hover:text-cyan-700"
            >
              See who it&apos;s built for &mdash; GCs, MEP, civil, specialty, and more
              <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" />
            </a>
          </div>
        </div>
      </section>

      <section id="built-for-construction" className="border-t border-zinc-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="grid items-start gap-16 lg:grid-cols-5">
            <div className="lg:col-span-3">
              <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.3)]">
                Why Maestro
              </p>
              <h2 className="mb-6 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
                Not a chatbot.
                <br />
                Not a dashboard.
                <br />
                An operating system.
              </h2>
              <p className="mb-10 text-lg leading-relaxed text-zinc-700">
                Maestro Fleet was built by people who have run construction projects. It understands plan sets,
                disciplines, schedule logic, and the way work actually moves on a jobsite. It runs on your hardware,
                your plans stay on your machine, and the intelligence is always available.
              </p>
              <div className="space-y-4">
                {[
                  'Reads architectural, structural, mechanical, electrical, plumbing, and civil drawings',
                  'Ingests PDFs and builds a searchable knowledge store per project',
                  'Tracks activities, milestones, inspections, deliveries, and constraints',
                  'Communicates through Telegram and works from the jobsite, the truck, or the office',
                  'Runs entirely on your hardware so your plans never leave your machine',
                ].map((item) => (
                  <div key={item} className="flex items-start gap-3">
                    <div className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-500 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
                    <span className="leading-relaxed text-zinc-800">{item}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="lg:col-span-2">
              <div className="relative overflow-hidden rounded-2xl border border-cyan-900/50 bg-zinc-950 p-7 text-sm font-mono shadow-[0_15px_40px_-15px_rgba(6,182,212,0.3)]">
                <div
                  className="absolute inset-0 opacity-[0.2]"
                  style={{
                    backgroundImage:
                      'linear-gradient(#0891b2 1px, transparent 1px), linear-gradient(90deg, #0891b2 1px, transparent 1px)',
                    backgroundSize: '20px 20px',
                  }}
                />
                <div className="pointer-events-none absolute right-0 top-0 h-32 w-32 rounded-full bg-cyan-500/15 blur-[40px]" />

                <div className="relative space-y-3">
                  <div className="mb-4 text-[10px] font-bold uppercase tracking-widest text-cyan-400 drop-shadow-[0_0_5px_rgba(34,211,238,0.5)]">
                    Local Architecture
                  </div>
                  <div className="flex items-center gap-3 rounded-lg border border-cyan-800/50 bg-zinc-900 px-4 py-3 shadow-[0_0_15px_rgba(6,182,212,0.1)]">
                    <HardDrive className="h-4 w-4 shrink-0 text-cyan-400" />
                    <span className="font-sans font-medium text-zinc-100">Your hardware</span>
                  </div>
                  <div className="flex justify-center">
                    <div className="h-4 w-px bg-cyan-800/50 shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
                  </div>
                  <div className="rounded-lg border border-emerald-500/40 bg-emerald-950/30 p-3 shadow-[0_0_20px_rgba(16,185,129,0.15)] backdrop-blur-sm">
                    <div className="mb-3 flex items-center gap-2">
                      <Cpu className="h-3.5 w-3.5 text-emerald-400 drop-shadow-[0_0_5px_rgba(52,211,153,0.8)]" />
                      <div className="text-[10px] font-bold uppercase tracking-widest text-emerald-400 drop-shadow-[0_0_5px_rgba(52,211,153,0.5)]">
                        OpenClaw Runtime
                      </div>
                    </div>
                    <div className="space-y-3 rounded-lg border border-cyan-800/60 bg-zinc-900/90 p-4 shadow-[0_0_15px_rgba(6,182,212,0.1)]">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-cyan-500">Maestro Fleet</div>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="rounded border border-cyan-700/50 bg-zinc-800 py-2 text-center font-sans text-xs font-medium text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.1)]">
                          Commander
                        </div>
                        <div className="rounded border border-cyan-700/50 bg-zinc-800 py-2 text-center font-sans text-xs font-medium text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.1)]">
                          Project Agents
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div className="rounded border border-zinc-800 bg-zinc-900 py-1.5 text-center font-sans text-[10px] text-zinc-400">
                          Command Center
                        </div>
                        <div className="rounded border border-zinc-800 bg-zinc-900 py-1.5 text-center font-sans text-[10px] text-zinc-400">
                          Knowledge Stores
                        </div>
                        <div className="rounded border border-zinc-800 bg-zinc-900 py-1.5 text-center font-sans text-[10px] text-zinc-400">
                          Workspaces
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-center gap-6 pt-3 text-[10px] font-bold uppercase tracking-widest text-cyan-600/80">
                    <span>Isolated</span>
                    <span>Secure</span>
                    <span>Local</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-t border-zinc-200 bg-zinc-50">
        <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="grid items-center gap-16 lg:grid-cols-2">
            <div>
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-200/50 bg-emerald-100/50 px-3 py-1.5">
                <Cpu className="h-4 w-4 text-emerald-600" />
                <span className="text-[11px] font-bold uppercase tracking-widest text-emerald-700">The Platform</span>
              </div>
              <h2 className="mb-6 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
                Powered by OpenClaw.
              </h2>
              <p className="mb-6 text-lg leading-relaxed text-zinc-800">
                Maestro Fleet is built on OpenClaw, an open-source agent runtime designed for production workloads. It
                handles the hard problems of running persistent AI agents so Maestro can focus entirely on construction
                intelligence.
              </p>
              <p className="mb-8 leading-relaxed text-zinc-700">
                Every agent in your fleet runs through the OpenClaw runtime: lifecycle management, message routing,
                persistent memory, Telegram connectivity, and local execution. It is the foundation that makes Maestro
                possible.
              </p>
              <a
                href="https://openclaw.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="group inline-flex items-center gap-2 text-sm font-bold text-emerald-600 transition-colors hover:text-emerald-700"
              >
                Learn more at openclaw.ai
                <ExternalLink className="h-4 w-4 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </a>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {[
                {
                  title: 'Agent Lifecycle',
                  desc: 'Spawn, monitor, and govern agents that run continuously on your hardware.',
                  icon: '◉',
                },
                {
                  title: 'Telegram Native',
                  desc: 'Every agent gets a real messaging identity your team can text from the field.',
                  icon: '◈',
                },
                {
                  title: 'Persistent Memory',
                  desc: 'Conversations, decisions, and project context survive restarts and updates.',
                  icon: '◇',
                },
                {
                  title: 'Local Execution',
                  desc: 'Runs on your machine. Your data, your plans, your control. Nothing leaves.',
                  icon: '▣',
                },
              ].map((item) => (
                <div
                  key={item.title}
                  className="rounded-xl border border-zinc-200/80 bg-white p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_10px_20px_-10px_rgba(0,0,0,0.05)]"
                >
                  <div className="mb-4 font-mono text-xl text-emerald-500">{item.icon}</div>
                  <h3 className="mb-2 text-sm font-bold text-zinc-950">{item.title}</h3>
                  <p className="text-xs leading-relaxed text-zinc-700">{item.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="get-started" className="border-t border-zinc-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-24 md:py-32">
          <div className="mx-auto mb-16 max-w-2xl text-center">
            <p className="mb-4 text-sm font-bold uppercase tracking-widest text-cyan-600 drop-shadow-[0_0_8px_rgba(6,182,212,0.3)]">Get Started</p>
            <h2 className="mb-5 text-3xl font-bold leading-tight tracking-tight text-zinc-950 md:text-4xl">
              We deploy it. You run your projects.
            </h2>
            <p className="text-lg leading-relaxed text-zinc-700">
              We remote into your machine, configure the entire fleet with you, set up your Commander, create your
              first project agents, ingest your plans, and make sure everything is running before we leave. You are
              operational the same day.
            </p>
            <p className="mt-5 text-sm font-medium leading-relaxed text-zinc-400">
              The website flow is consultation-first. Billing is handled after scope confirmation and onboarding.
            </p>
          </div>

          <div className="mx-auto grid max-w-4xl gap-8 md:grid-cols-2">
            <div className="relative rounded-3xl border border-zinc-200/80 bg-zinc-50 p-10">
              <div className="absolute -top-3 left-8">
                <span className="rounded-full bg-zinc-950 px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest text-white shadow-sm">
                  One-time setup
                </span>
              </div>
              <div className="mt-4">
                <div className="mb-2 flex items-baseline gap-1">
                  <span className="text-5xl font-extrabold tracking-tighter text-zinc-950 tabular-nums">{setupPriceLabel}</span>
                </div>
                <p className="mb-8 font-medium text-zinc-700">Full fleet deployment and configuration, invoiced after consultation</p>
                <div className="space-y-4">
                  {[
                    'Remote session and full system setup on your machine',
                    'Commander configured and connected to Telegram',
                    'First project agents created and plan sets ingested',
                    'Walkthrough of the Command Center and field workflow',
                    'Help documentation installed on your machine',
                    'Operational same day',
                  ].map((item) => (
                    <div key={item} className="flex items-start gap-3 text-sm">
                      <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
                      <span className="leading-relaxed text-zinc-800">{item}</span>
                    </div>
                  ))}
                </div>
                <CtaLink
                  href={primaryContactHref}
                  className="group mt-10 inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-6 py-3.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_25px_rgba(6,182,212,0.4)]"
                >
                  <Calendar className="h-4 w-4 text-cyan-400" />
                  Book a Consultation
                  <ArrowUpRight className="h-4 w-4 text-cyan-400 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </CtaLink>
              </div>
            </div>

            <div className="relative rounded-3xl border border-zinc-200/80 bg-white p-10 shadow-[0_4px_20px_-10px_rgba(0,0,0,0.05)]">
              <div className="absolute -top-3 left-8">
                <span className="rounded-full border border-zinc-200 bg-zinc-100 px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest text-zinc-600">
                  Optional
                </span>
              </div>
              <div className="mt-4">
                <div className="mb-2 flex items-baseline gap-1">
                  <span className="text-5xl font-extrabold tracking-tighter text-zinc-950 tabular-nums">{monthlyPriceLabel}</span>
                </div>
                <p className="mb-8 font-medium text-zinc-700">Ongoing maintenance and support, available after setup</p>
                <div className="space-y-4">
                  {[
                    'Fleet health monitoring and proactive maintenance',
                    'New project agent creation as you win work',
                    'Plan set ingestion for new and updated drawings',
                    'System updates and runtime upgrades',
                    'Direct support line for your team',
                    'Commander tuning and optimization over time',
                  ].map((item) => (
                    <div key={item} className="flex items-start gap-3 text-sm">
                      <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-zinc-300" />
                      <span className="leading-relaxed text-zinc-800">{item}</span>
                    </div>
                  ))}
                </div>
                <CtaLink
                  href={primaryContactHref}
                  className="group mt-10 inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-6 py-3.5 text-sm font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_25px_rgba(6,182,212,0.4)]"
                >
                  <Calendar className="h-4 w-4 text-cyan-400" />
                  Book a Consultation
                  <ArrowUpRight className="h-4 w-4 text-cyan-400 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </CtaLink>
              </div>
            </div>
          </div>

          <div className="mt-20 text-center">
            <CtaLink
              href={primaryContactHref}
              className="group inline-flex items-center justify-center gap-2 rounded-xl bg-zinc-950 px-10 py-4 text-base font-semibold text-white shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_20px_rgba(6,182,212,0.2)] transition-all duration-300 hover:-translate-y-0.5 hover:bg-zinc-900 hover:shadow-[0_0_0_1px_rgba(255,255,255,0.1)_inset,0_0_30px_rgba(6,182,212,0.4)]"
            >
              <Calendar className="h-4 w-4 text-cyan-400" />
              Book a Consultation
              <ArrowUpRight className="h-4 w-4 text-cyan-400 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
            </CtaLink>
            <p className="mt-5 text-sm font-medium text-zinc-400">Pick a time and we will talk through your operation.</p>
          </div>
        </div>
      </section>

      <EmailSignupSection />

      <footer className="border-t border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between px-6 py-10 text-sm text-zinc-400 md:flex-row">
          <div className="flex items-center gap-2.5">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-zinc-950 shadow-[0_0_10px_rgba(6,182,212,0.2)]">
              <span className="font-mono text-[9px] font-bold tracking-wider text-cyan-400">MF</span>
            </div>
            <span className="font-medium">&copy; {new Date().getFullYear()} Maestro Systems</span>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-4 md:mt-0">
            <a
              href="https://openclaw.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-xs font-medium text-zinc-400 transition-colors hover:text-emerald-600"
            >
              <Cpu className="h-3.5 w-3.5" />
              Built on OpenClaw
            </a>
            <span className="text-zinc-200">·</span>
            <a href="/built-for" className="text-xs font-medium text-zinc-400 transition-colors hover:text-zinc-700">Built For</a>
            <a href="/privacy" className="text-xs font-medium text-zinc-400 transition-colors hover:text-zinc-700">Privacy</a>
            <a href="/terms" className="text-xs font-medium text-zinc-400 transition-colors hover:text-zinc-700">Terms</a>
            <a href="/refund" className="text-xs font-medium text-zinc-400 transition-colors hover:text-zinc-700">Refunds</a>
            <span className="text-zinc-200">·</span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-300">Built for the dirt.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
