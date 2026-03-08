import { addSubscriberToSequence, addTagByEmail, getKitConfig, removeTagByEmail, upsertSubscriber } from './kit.js';

function normalizeLifecycle(value) {
  return String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
}

export function inferKitLifecycle({ amount, description } = {}) {
  const normalizedDescription = String(description || '').trim().toLowerCase();
  const normalizedAmount = Number(amount);

  if (normalizedDescription.includes('monthly') || normalizedDescription.includes('coverage')) {
    return 'monthly';
  }

  if (normalizedDescription.includes('setup') || normalizedDescription.includes('deployment')) {
    return 'setup';
  }

  if (normalizedAmount === 1500) {
    return 'setup';
  }

  if (normalizedAmount === 400) {
    return 'monthly';
  }

  return 'none';
}

export async function syncKitLifecycleByEmail({ email, firstName = '', lifecycle }) {
  if (!email) {
    return { email: '', lifecycle: 'none', synced: false };
  }

  const normalizedLifecycle = normalizeLifecycle(lifecycle);
  if (!normalizedLifecycle || normalizedLifecycle === 'none') {
    return { email, lifecycle: 'none', synced: false };
  }

  const kitConfig = getKitConfig();
  await upsertSubscriber({ email, firstName });

  if (kitConfig.customerTagId) {
    await addTagByEmail(kitConfig.customerTagId, email);
  }

  if (normalizedLifecycle === 'setup') {
    await addTagByEmail(kitConfig.setupPaidTagId, email);
    await addSubscriberToSequence(kitConfig.setupOnboardingSequenceId, email);
  }

  if (normalizedLifecycle === 'monthly') {
    await addTagByEmail(kitConfig.monthlyActiveTagId, email);
    await removeTagByEmail(kitConfig.formerMonthlyTagId, email);
    await addSubscriberToSequence(kitConfig.monthlyOnboardingSequenceId, email);
  }

  if (normalizedLifecycle === 'former_monthly') {
    await removeTagByEmail(kitConfig.monthlyActiveTagId, email);
    await addTagByEmail(kitConfig.formerMonthlyTagId, email);
  }

  return { email, lifecycle: normalizedLifecycle, synced: true };
}

export async function syncKitConsultationBookingByEmail({ email, firstName = '' }) {
  if (!email) {
    return { email: '', synced: false };
  }

  const kitConfig = getKitConfig();
  await upsertSubscriber({ email, firstName });

  if (kitConfig.consultationBookedTagId) {
    await addTagByEmail(kitConfig.consultationBookedTagId, email);
  }

  if (kitConfig.consultationBookedSequenceId) {
    await addSubscriberToSequence(kitConfig.consultationBookedSequenceId, email);
  }

  return { email, synced: true };
}

export async function syncKitMonthlySubscriptionStatus({ email, isActive }) {
  if (!email) {
    return { email: '', synced: false };
  }

  const lifecycle = isActive ? 'monthly' : 'former_monthly';
  return syncKitLifecycleByEmail({ email, firstName: '', lifecycle });
}
