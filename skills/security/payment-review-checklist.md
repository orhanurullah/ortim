---
name: payment-review-checklist
description: Human review checklist for payment, billing, and financial transaction tasks.
audience: [reviewer, human]
triggers:
  keywords:
    - payment
    - billing
    - invoice
    - checkout
    - credit-card
    - debit-card
    - stripe
    - paypal
    - iyzico
    - adyen
    - refund
    - subscription
    - pci-dss
---

# Payment review checklist

This task handles payment / billing / financial transactions. PCI-DSS exposure + direct financial impact mean a single bug is expensive. Human review is mandatory before merge.

## PCI scope

- [ ] Does this code touch PAN (primary account number, CVV, full card data)?
  - **YES** → you are in PCI-DSS scope. Stop. This usually means use a tokenization provider (Stripe Elements, Adyen drop-in, iyzico checkout form). Raw card data should NEVER pass through your backend.
  - **NO** → tokenized references only. Verify the token can only redeem to the user who owns it.
- [ ] PCI scope minimization: every system component that touches PAN is in scope for audit. Push tokenization to the edge.

## Provider integration

- [ ] API key for Stripe/Adyen/iyzico in env var / secret manager — NEVER in code or repo.
- [ ] Webhook signature verified on every incoming webhook. Replay protection (event ID dedup, ≥ 24h window).
- [ ] Test mode vs live mode clearly distinguished in code. No accidental live-key in dev.
- [ ] Idempotency keys used on payment creation — same key returns same outcome, never double-charges.

## Amount handling

- [ ] Money stored as integer minor units (cents, kuruş) — NEVER as float. (`499` cents, not `4.99`.)
- [ ] Currency stored alongside amount. Never assume.
- [ ] Server-side authoritative — client-side amount sent in the request is treated as a hint, the actual charge is computed server-side from the cart/subscription.
- [ ] No rounding-down in the user's favor (`floor`); no rounding-up against the user (`ceil`). Use banker's rounding or explicit decision documented.

## Authorization & authentication

- [ ] User authentication required before any charge. Re-authenticate for high-value transactions / new cards (SCA / 3DS).
- [ ] Authorization: user can only charge / refund / view their own transactions. IDOR check on `transaction_id`.
- [ ] Admin actions (manual refund, plan adjustment) logged with who-did-what.

## State machine

- [ ] Payment status states documented: pending → authorized → captured → settled, OR failed / refunded / disputed. No status backtracking unless explicit (refund creates a new entry).
- [ ] Reconciliation job to detect drift between provider state and your DB (provider's webhook may miss; poll periodically).
- [ ] Failed payment handling: clear path forward (retry / cancel / contact support).

## Refunds & disputes

- [ ] Refund endpoint logs requester, reason, amount, original transaction.
- [ ] Partial refunds supported correctly (subtract from refundable balance, not from original amount).
- [ ] Dispute notifications surface in admin UI within 1 day.

## Subscriptions & recurring

- [ ] Renewal failure handling (failed retry → grace period → cancel).
- [ ] Proration policy documented for plan changes.
- [ ] Cancellation effective immediately on user action (not "at end of period" without explicit choice).
- [ ] Invoice generated + emailed for every renewal.

## Tax & compliance

- [ ] VAT / sales tax computed correctly per buyer location.
- [ ] Receipts include legal entity, VAT/tax number, currency, line items.
- [ ] Subscriber address verification for tax jurisdiction.

## Logs & observability

- [ ] No CVV, full PAN, or expiry-with-PAN in logs. Last 4 + brand OK.
- [ ] Every payment attempt logged: outcome, amount, currency, user, provider transaction ID.
- [ ] Alert on payment failure spike, refund spike, dispute.

## Testing

- [ ] Provider sandbox / test mode used for integration tests.
- [ ] Test card numbers used (`4242 4242 4242 4242` for Stripe, etc.). Never real cards in tests.
- [ ] Webhook signature verification has a negative test (wrong signature must reject).
- [ ] Idempotency tested (same idempotency key, two calls, one charge).
- [ ] Refund flow tested with full + partial amounts.

## When in doubt

If something feels like it might double-charge or fail to refund, write the test before fixing the code. Payments bugs are visible to the user immediately and cost trust.

If this checklist surfaces an issue, fix it before re-running `ortim execute <id> <task> --human-reviewed`.
