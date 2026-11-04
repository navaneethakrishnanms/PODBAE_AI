/** Drop-in seam for Stripe / Lemon Squeezy: implement PaymentProvider and return it from getPaymentProvider. */
export type PaidTier = 'date' | 'commit';

export interface CheckoutInput {
  userId: number;
  email: string;
  tier: PaidTier;
}
export interface CheckoutSession {
  provider: string;
  tier: PaidTier;
  /** Where the browser goes to pay. */
  checkoutUrl: string;
}
export interface PaymentProvider {
  name: string;
  createCheckout(input: CheckoutInput): Promise<CheckoutSession>;
  /** True if this user has an open checkout for the tier (mock: set by createCheckout). */
  verifyPayment(userId: number, tier: PaidTier): Promise<boolean>;
}

/** MOCK: sends the user to the in-app /mock-checkout page; "paying" there upgrades the tier locally. */
export class MockPaymentProvider implements PaymentProvider {
  name = 'mock';
  private pending = new Map<number, PaidTier>();
  async createCheckout(input: CheckoutInput): Promise<CheckoutSession> {
    this.pending.set(input.userId, input.tier);
    return { provider: this.name, tier: input.tier, checkoutUrl: `/mock-checkout?tier=${input.tier}` };
  }
  async verifyPayment(userId: number, tier: PaidTier) {
    const ok = this.pending.get(userId) === tier;
    if (ok) this.pending.delete(userId);
    return ok;
  }
}

const provider: PaymentProvider = new MockPaymentProvider();
export function getPaymentProvider(): PaymentProvider {
  return provider;
}
