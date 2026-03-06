import { addSubscriberToSequence, addTagByEmail, getKitConfig, removeTagByEmail, upsertSubscriber } from '../_lib/kit.js';
import { requireEnv } from '../_lib/env.js';
import {
  classifyPurchase,
  getCheckoutSessionSummary,
  getCustomerEmail,
  getStripeClient,
  getStripeConfig,
} from '../_lib/stripe.js';

async function syncKitForCheckoutCompleted(stripe, session) {
  const summary = await getCheckoutSessionSummary(stripe, session.id);
  const purchaseType = classifyPurchase({
    session,
    priceIds: summary.priceIds,
    ...getStripeConfig(),
  });

  const email =
    session.customer_details?.email ||
    session.customer_email ||
    (await getCustomerEmail(stripe, typeof session.customer === 'string' ? session.customer : session.customer?.id));

  if (!email) {
    return { purchaseType, email: '' };
  }

  const firstName = session.customer_details?.name?.split(' ')[0] ?? '';
  const kitConfig = getKitConfig();

  await upsertSubscriber({ email, firstName });

  if (kitConfig.customerTagId) {
    await addTagByEmail(kitConfig.customerTagId, email);
  }

  if (purchaseType === 'setup') {
    await addTagByEmail(kitConfig.setupPaidTagId, email);
    await addSubscriberToSequence(kitConfig.setupOnboardingSequenceId, email);
  }

  if (purchaseType === 'monthly') {
    await addTagByEmail(kitConfig.monthlyActiveTagId, email);
    await addSubscriberToSequence(kitConfig.monthlyOnboardingSequenceId, email);
  }

  return { purchaseType, email };
}

async function syncKitForSubscriptionChange(stripe, subscription, isActive) {
  const monthlyPriceId = getStripeConfig().monthlyPriceId;
  const hasManagedMonthlyPrice = subscription.items.data.some((item) => {
    const priceId = typeof item.price === 'string' ? item.price : item.price?.id;
    return priceId && priceId === monthlyPriceId;
  });

  if (!hasManagedMonthlyPrice) {
    return { email: '', synced: false };
  }

  const email = await getCustomerEmail(
    stripe,
    typeof subscription.customer === 'string' ? subscription.customer : subscription.customer?.id,
  );

  if (!email) {
    return { email: '', synced: false };
  }

  const kitConfig = getKitConfig();
  await upsertSubscriber({ email, firstName: '' });

  if (isActive) {
    await addTagByEmail(kitConfig.customerTagId, email);
    await addTagByEmail(kitConfig.monthlyActiveTagId, email);
    await removeTagByEmail(kitConfig.formerMonthlyTagId, email);
  } else {
    await removeTagByEmail(kitConfig.monthlyActiveTagId, email);
    await addTagByEmail(kitConfig.formerMonthlyTagId, email);
  }

  return { email, synced: true };
}

export default {
  async fetch(request) {
    if (request.method !== 'POST') {
      return Response.json({ error: 'Method not allowed.' }, { status: 405, headers: { Allow: 'POST' } });
    }

    const signature = request.headers.get('stripe-signature');
    if (!signature) {
      return Response.json({ error: 'Missing Stripe signature.' }, { status: 400 });
    }

    try {
      const stripe = getStripeClient();
      const rawBody = await request.text();
      const event = stripe.webhooks.constructEvent(rawBody, signature, requireEnv('STRIPE_WEBHOOK_SECRET'));

      let result = { ignored: true, type: event.type };

      switch (event.type) {
        case 'checkout.session.completed':
          result = await syncKitForCheckoutCompleted(stripe, event.data.object);
          break;
        case 'customer.subscription.created':
          result = await syncKitForSubscriptionChange(stripe, event.data.object, true);
          break;
        case 'customer.subscription.updated': {
          const activeStatuses = new Set(['active', 'trialing', 'past_due']);
          result = await syncKitForSubscriptionChange(
            stripe,
            event.data.object,
            activeStatuses.has(event.data.object.status),
          );
          break;
        }
        case 'customer.subscription.deleted':
          result = await syncKitForSubscriptionChange(stripe, event.data.object, false);
          break;
        default:
          result = { ignored: true, type: event.type };
          break;
      }

      return Response.json({ received: true, result });
    } catch (error) {
      return Response.json(
        {
          error: 'Webhook processing failed.',
          message: error instanceof Error ? error.message : 'Unknown error.',
        },
        { status: 400 },
      );
    }
  },
};
