# Llink prepaid credits

## Commercial rule

- Reference price: **1 credit = USD 0.01**.
- Think is the only service that calculates the CDF checkout amount.
- Llink never accepts a client-supplied payment amount.
- A Think payment is not a deposit into the Think monetary wallet. It creates a separate Llink credit purchase.
- Only a payment that Think has reconciled as `accepted` and whose purchase is `paid` can be granted to the Llink Firestore wallet.
- Purchase grants are idempotent by CinetPay public payment ID.

## Wallets

- `daily_free_balance`: replenished once per UTC day from `LLINK_DAILY_FREE_CREDITS` (default 5).
- `online_balance`: prepaid credits consumed by online AI requests.
- `offline_balance`: reserved for future offline entitlements; spending and checkout are disabled until device-bound signed authorization is implemented.
- `reserved_free` and `reserved_online`: amounts held before model execution.
- `credit_debt`: a safety ledger for actual usage that exceeds a reservation; further use is blocked until reconciled.

One credit represents 10,000 micro-USD. Costs are rounded up to whole credits. Daily free credits are used before paid Online credits. Unused reservations are released after provider completion or failure.

## API

- `GET /api/credits/catalog`
- `GET /api/credits/wallet`
- `POST /api/credits/checkout`
- `POST /api/credits/refresh`

Checkout and payment refresh require a Think-authenticated Llink session. Google sign-in remains available for legacy accounts, but cannot initiate a Think Mobile Money purchase.

## Think environment

Configure these values on Think:

- `LLINK_CDF_PER_USD`: approved CDF per USD exchange rate. The value must be positive and is used server-side.
- `LLINK_DAILY_FREE_CREDITS`: optional integer from 0 to 1,000; default 5.

Llink must also have `THINK_API_BASE_URL`, `THINK_SSO_SECRET`, and `THINK_SERVICE_TOKEN`. Think and Llink must use identical shared secrets.

## Gemini image generation

Work image generation uses the Gemini `gemini-3.1-flash-image` model through the server. Configure `GEMINI_API_KEY` on Llink. The API request uses the `v1beta` `generateContent` endpoint and `imageConfig` for aspect ratio and resolution. Image generation and image edits reserve credits before calling Gemini and settle the fixed published image-output estimate after success; a failed generation cancels the reservation.

Current estimates in this implementation:
- Standard (1K): 7 credits.
- HD (2K): 11 credits.

Provider pricing can change; review the Gemini pricing page before enabling production sales.

## Validation boundary

Sandbox and unit tests do not prove a real Mobile Money payment. Before production:
1. Configure the exchange rate and shared secrets.
2. Run the Think -> Llink -> CinetPay Sandbox purchase and refresh flow.
3. Confirm the wallet is credited exactly once after provider confirmation.
4. Verify no amount reaches the Think monetary wallet.
5. Only then deploy the reviewed PRs.
