text
## Research report: leaving Azure AD B2C + PayPro Global as the surviving system

All findings below come from live fetches on 2026-09-09. Every claim carries its source URL. Where an official page did not contain something, I say so.

---

## PART A — Leaving Azure AD B2C

### A1. Product status: end of sale confirmed, support "at least May 2030"

Official FAQ (page `ms.date` 2025-06-20, last updated 2026-06-11):

> "Effective **May 1, 2025** Azure AD B2C will no longer be available to purchase for new customers, but current Azure AD B2C customers can continue using the product. The product experience, including creating new tenants or user flows, will remain unchanged; however, new tenants can only be created with Azure AD B2C P1. Azure AD B2C P2 will be discontinued on March 15, 2026, for all customers. The operational commitments, including service level agreements (SLAs), security updates, and compliance, will also remain unchanged. We'll continue supporting Azure AD B2C until at least May 2030."

Additional P2 retirement detail on the same page: "All P2 tenants will be automatically switched to P1 on a rolling basis by the end of March 2026." The FAQ names Microsoft Entra External ID as the "next generation" product.

Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/faq

### A2. Refresh-token lifetime rules — the 24-hour SPA limit is real and not configurable

**B2C "Configure tokens" page** — configurable ranges:

- Access and ID token lifetime: "The default is 60 minutes (1 hour). The minimum (inclusive) is 5 minutes. The maximum (inclusive) is 1,440 minutes (24 hours)."
- Refresh token lifetime: "The default is 14 days. The minimum (inclusive) is one day. The maximum (inclusive) 90 days."
- Refresh token sliding window: `Bounded` or `No expiry`; "Lifetime length (days) … must be greater than or equal to the Refresh token lifetime value."
- Custom-policy metadata: `refresh_token_lifetime_secs` default 1,209,600 (14 d), min 86,400, max 7,776,000 (90 d); `rolling_refresh_token_lifetime_secs` default 7,776,000 (90 d), min 86,400, max 31,536,000 (365 d); `allow_infinite_rolling_refresh_token=true` disables the sliding window. Authorization codes expire after ~10 minutes and this "can't be configured".

And the key note, verbatim:

> "Single-page applications using the authorization code flow with PKCE always have a refresh token lifetime of 24 hours while mobile apps, desktop apps, and web apps do not experience this limitation."

Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/configure-tokens

**Microsoft identity platform "Refresh tokens" page** (applies to Entra ID, B2C and External ID):

> "Refresh tokens sent to a redirect URI registered as `spa` expire after 24 hours. Additional refresh tokens acquired using the initial refresh token carry over that expiration time, so apps must be prepared to rerun the authorization code flow using an interactive authentication to get a new refresh token every 24 hours. Users don't have to enter their credentials and usually don't even see any related user experience, just a reload of your application. The browser must visit the sign-in page in a top-level frame to show the login session."

Default lifetimes listed on the same page: "24 hours for single-page applications", "24 hours for apps that use email one-time passcode authentication flow", "90 days for all other scenarios".

Source: https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens

**Why**, from the third-party-cookies page: "Refresh tokens issued through the authorization code flow to `spa` redirect URIs have a 24-hour lifetime rather than a 90-day lifetime." … "In order to minimize the risk of stolen refresh tokens, SPAs are issued tokens valid for 24 hours only. After 24 hours, the app must acquire a new authorization code via a top-level frame visit to the login page."
Source: https://learn.microsoft.com/en-us/entra/identity-platform/reference-third-party-cookies-spas

**Diagnosis for your app:** the desktop app uses `@azure/msal-browser` against a `spa`-type redirect URI, so it is treated as a SPA regardless of the fact that it runs in a desktop shell. The refresh token hard-expires at 24 h and MSAL must do a top-level redirect to the B2C login page. In a packaged desktop webview the B2C session cookie is often unavailable (third-party-cookie blocking, no custom domain), so that "silent reload" turns into a full interactive login. No B2C token setting changes this; only a non-`spa` platform (public client mobile/desktop redirect with a native/loopback flow) gets the configurable 14–90-day refresh tokens.

### A3. Exporting all users incl. custom extension attributes via Microsoft Graph

**Listing users and page size** (Graph v1.0 "List users"): "The default and maximum page sizes are 100 and 999 user objects respectively, except when you specify `$select=signInActivity` … The `$count` and `$search` parameters are currently not available in Azure AD B2C tenants." Application permissions: `User.Read.All`, `User.ReadWrite.All`, `Directory.Read.All`, `Directory.ReadWrite.All`. The page also shows the B2C-specific filter form `$filter=identities/any(c:c/issuerAssignedId eq 'j.smith@yahoo.com' and c/issuer eq 'My B2C tenant')`.
Source: https://learn.microsoft.com/en-us/graph/api/user-list?view=graph-rest-1.0

**Pagination:** follow `@odata.nextLink` until absent; "Don't try to extract the `$skiptoken` … and use it in a different request"; keep the last successful nextLink for retries to avoid `DirectoryPageTokenNotFoundException`.
Source: https://learn.microsoft.com/en-us/graph/paging

**Properties you must `$select` explicitly** (they are not returned by default):
- `identities` — "Requires `$select` to retrieve." The `objectIdentity` items carry `signInType` (`emailAddress`, `userName`, or `federated`), `issuer` (local = tenant domain, social = issuer name such as `facebook.com`) and `issuerAssignedId` (email for local accounts; "the federated account unique identifier" for social).
  Sources: https://learn.microsoft.com/en-us/graph/api/resources/user?view=graph-rest-1.0 and https://learn.microsoft.com/en-us/azure/active-directory-b2c/user-profile-attributes
- Extension attributes — named `extension_<b2c-extensions-app clientId without hyphens>_<Name>`; "Directory extensions: Returned only with `$select`." B2C doc: "The property is returned by default through the `beta` endpoint, but only on `$select` through the `v1.0` endpoint."
  Sources: https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0 , https://learn.microsoft.com/en-us/azure/active-directory-b2c/microsoft-graph-operations , https://learn.microsoft.com/en-us/azure/active-directory-b2c/user-profile-attributes
- Also select `creationType` (`LocalAccount` for B2C local users), `accountEnabled`, `createdDateTime`, `otherMails`, `displayName`.

B2C query restriction: "Azure AD B2C currently doesn't support advanced query capabilities on directory objects … no support for `$count`, `$search` … and Not (`not`), Not equals (`ne`), and Ends with (`endsWith`) operators in `$filter`."
Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/microsoft-graph-operations

**Passwords cannot be read out.** I found no official page containing a literal sentence "password hashes cannot be exported", so I am stating this by construction:
- Graph exposes `passwordProfile.password` only as a create/update input ("This property is required when a user is created. It can be updated…"); there is no read operation for it. Source: https://learn.microsoft.com/en-us/graph/api/resources/passwordprofile?view=graph-rest-1.0
- Microsoft's own B2C→External ID guidance requires "If you don't have access to the plaintext passwords, you should set a random password for now that will be updated later as part of the password migration process", then harvests the real password at the user's next sign-in. That machinery exists precisely because stored credentials cannot be exported. Source: https://learn.microsoft.com/en-us/entra/external-id/customers/how-to-migrate-users
- Social accounts have no password anyway: "For a federated (social) identity, the passwordProfile attribute isn't required." Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/user-profile-attributes

**Throttling relevant to a 10k–50k export:** Identity/directory limits are resource-unit based per app per tenant: "S: 3,500 ResourceUnits per 10 seconds, M: 5,000 … L: 8,000" (S/M/L = tenant size), a `GET /users` costs 2 RU, tenant-wide write quota 18,000 requests per 5 minutes. At 999 users/page, 50k users is ~51 GET calls — throttling is a non-issue for the read; it only matters if you bulk-write into a new Entra tenant. Source: https://learn.microsoft.com/en-us/graph/throttling-limits (the External ID migration doc also points here: https://learn.microsoft.com/en-us/entra/external-id/customers/migrate-from-b2c-to-external-id)

### A4. Custom policies can call a REST API during sign-in — official "lazy migration" pattern exists

- RESTful technical profile: "Azure Active Directory B2C (Azure AD B2C) provides support for integrating your own RESTful service. Azure AD B2C sends data to the RESTful service in an input claims collection and receives data back in an output claims collection." Auth types: `None`, `Basic`, `Bearer`, `ClientCertificate` (recommended), `ApiKeyHeader`; `SendClaimsIn` Body/Form/Header/Url/QueryString; errors returned as HTTP 4xx with `"status": 409` JSON and a `userMessage`.
  Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/restful-technical-profile
- Where it can run: "You can add a REST API call at any step in the user journey defined by a custom policy. For example, you can call a REST API: During sign-in, just before Azure AD B2C validates the credentials. Immediately after sign-in. Before Azure AD B2C creates a new account … After … Before Azure AD B2C issues an access token." Scenarios include "run a user migration process". Timeout: "The default timeout is 10 seconds for custom policies and 5 seconds for user flows. The default retry count is one".
  Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/api-connectors-overview
- B2C's own "seamless migration" uses exactly this: a sign-in-time REST call gets the entered credentials, validates them, and a boolean extension attribute tracks who has been migrated. Sample: https://aka.ms/b2c-account-seamless-migration. Security note: "You must protect your REST API against brute-force attacks."
  Source: https://learn.microsoft.com/en-us/azure/active-directory-b2c/user-migration
- Microsoft describes the reverse direction (out of B2C) the same way: "In the B2C-initiated pattern, applications remain on Azure AD B2C endpoints while credentials are harvested in the background. A B2C custom policy calls a REST API to validate credentials against the legacy IdP and write them to the corresponding External ID accounts."
  Source: https://learn.microsoft.com/en-us/entra/external-id/customers/migrate-from-b2c-to-external-id

So a lazy migration to any new IdP is feasible: at each local-account sign-in the custom policy posts email + password (+ objectId, identities, extension claims) to your REST API, which creates/updates the user in the new IdP and flips a `extension_..._migrated` flag. Social-account users need no password step at all.

### A5. Microsoft Entra External ID as successor (brief)

- **Official migration path:** yes. "Plan your migration" (standard vs. High Scale Compatibility mode; HSC only for ~5M+ objects), "Migrate from Azure AD B2C" (4 stages: assess, prepare tenant, migrate users/credentials via bulk Graph + JIT `OnPasswordSubmit` extension or B2C-initiated harvesting, validate/cutover), plus a sample tool at https://github.com/microsoft/b2c-to-meeid-migration-tool/.
  Sources: https://learn.microsoft.com/en-us/entra/external-id/customers/plan-your-migration-from-b2c-to-external-id , https://learn.microsoft.com/en-us/entra/external-id/customers/migrate-from-b2c-to-external-id , https://learn.microsoft.com/en-us/entra/external-id/customers/how-to-migrate-users
- **Feature gaps that matter to you:** "Custom policies (IEF): Custom policy logic must be recreated using custom authentication extensions. One-to-one parity isn't guaranteed." and "Social identity providers configured through B2C custom policies … Third-party identity providers configured through B2C custom policies aren't supported." External tenants support Google, Facebook, Apple, Microsoft Entra ID, custom OIDC, SAML/WS-Fed — **GitHub is not mentioned anywhere on the identity-providers page**. (GitHub is OAuth2-only, not OIDC, so custom-OIDC federation would not cover it — that part is my inference, not a doc statement.)
  Sources: https://learn.microsoft.com/en-us/entra/external-id/customers/migrate-from-b2c-to-external-id , https://learn.microsoft.com/en-us/entra/external-id/customers/concept-authentication-methods-customers , https://learn.microsoft.com/en-us/entra/external-id/customers/concept-supported-features-customers
- **Cost:** MAU-based; "MAU billing applies to all users in an external tenant regardless of their UserType setting." Microsoft's pricing page: "The External ID core features are free for your first 50,000 monthly active users." The per-MAU price above 50k could not be retrieved — the Azure pricing page renders "$-" placeholders (JS-populated), so I cannot cite a number. Add-ons: SMS per verification attempt, M2M per transaction, Go-Local per MAU (Australia/Japan only).
  Sources: https://learn.microsoft.com/en-us/entra/external-id/external-identities-pricing , https://www.microsoft.com/en-us/security/business/microsoft-entra-pricing , https://azure.microsoft.com/en-us/pricing/details/microsoft-entra-external-id/
- **Same 24-hour SPA restriction: yes.** External ID token lifetimes are "Same as workforce", and the workforce doc says "Refresh and session token lifetimes are no longer configurable through token lifetime policies. Microsoft Entra ID uses only the default values" — which are the 24 h SPA / 24 h email-OTP / 90 d defaults quoted in A2. A Microsoft-staff Q&A answer confirms: "24 hours for single-page applications … 90 days for all other scenarios" and "there isn't a user-flow setting, Conditional Access policy or similar knob that pushes it past 24 hours." External ID is actually *worse* than B2C here: B2C lets you tune non-SPA refresh tokens (14–90 d, rolling up to 365 d), External ID does not.
  Sources: https://learn.microsoft.com/en-us/entra/external-id/customers/concept-supported-features-customers , https://learn.microsoft.com/en-us/entra/identity-platform/configurable-token-lifetimes , https://learn.microsoft.com/en-us/answers/questions/5859191/clarification-on-refresh-token-lifetime-for-extern , https://learn.microsoft.com/en-us/answers/questions/5612977/is-this-possible-to-configure-token-lifetime-in-en
- Service limits: 300,000 objects per external tenant (extendable), 200 requests/s per tenant, 20/s per IP. Source: https://learn.microsoft.com/en-us/entra/external-id/customers/reference-service-limits

---

## PART B — PayPro Global

### B1. `x-` custom parameters and IPN structure

**Custom parameters:** "Custom fields are passed via URL using the format `&x-customfield1=value1`"; "Any text after `x-` can be `=` to any text here, for example: `&x-testuser=123`". They come back:
- in the webhook as `ORDER_CUSTOM_FIELDS=x-testuser=123`;
- from `POST /api/Orders/GetOrderDetails` as `"customFields": [{"customFieldKey": "x-testuser", "customFieldValue": "123"}]`;
- on the order details page in the dashboard;
- in the "PayPro Global Order Notification" email.
Source: https://developers.payproglobal.com/docs/checkout-pages/custom-parameters/
URL-parameter reference: "x-<customFieldName> (string): Any custom value that needs to be passed to the checkout page and received back via webhook." There is **no dedicated customer-id/external-id parameter**; `x-` fields are the only mechanism. `ipn-domain`: "The value of ipn-domain is a filter for the list of IPN URLs."
Source: https://developers.payproglobal.com/docs/checkout-pages/url-parameters/

**IPN types** (exact `IPN_TYPE_ID` / `IPN_TYPE_NAME` — note the spelling `SubscriptionChargeSucceed`, no "-ed"):
1 OrderCharged, 2 OrderRefunded, 3 OrderChargedBack, 4 OrderDeclined, 5 OrderPartiallyRefunded, **6 SubscriptionChargeSucceed**, **7 SubscriptionChargeFailed**, **8 SubscriptionSuspended**, **9 SubscriptionRenewed**, **10 SubscriptionTerminated**, **11 SubscriptionFinished**, 12 LicenseRequested, 13 TrialCharge, 14 OrderChargedBackWon, 15 OrderCustomerInformationChanged ("when the customer's billing email is changed"), 16 InstantLeadNotification, 17 OrderOnWaiting, 21 SubscriptionPaymentInfoChanged.

**Format:** HTTP POST, "The Content-Type header of the request is application/x-www-form-urlencoded." Your endpoint must answer HTTP 200: "All other response codes indicate some kind of failure."

**Payload fields** (one shared parameter reference for all types; only some are annotated "sent only in IPN type N"): `ORDER_ID`, `ORDER_STATUS_ID/_NAME` (Waiting, Canceled, Refunded, Chargeback, Processed), `IPN_TYPE_ID/_NAME`, `PRODUCT_ID`, `ORDER_ITEM_ID`, `ORDER_ITEM_SKU`, `CUSTOMER_ID` ("Integer customer ID"), `CUSTOMER_EMAIL`, `CUSTOMER_FIRST_NAME/LAST_NAME`, `CUSTOMER_COUNTRY_CODE`, **`ORDER_CUSTOM_FIELDS`** ("Custom fields used in the order" — no type restriction annotated), **`CHECKOUT_QUERY_STRING`** ("Checkout query string" — i.e. your whole original URL query incl. `x-azure-user-id`), `SUBSCRIPTION_ID`, `SUBSCRIPTION_STATUS_ID/_NAME` (Active, Suspended, Terminated, Finished), `SUBSCRIPTION_NEXT_CHARGE_DATE`, `SUBSCRIPTION_NEXT_CHARGE_AMOUNT`, `SUBSCRIPTION_NEXT_CHARGE_CURRENCY_CODE`, `SUBSCRIPTION_INITIAL_ORDER_ID`, `SUBSCRIPTION_RENEWAL_TYPE` (Manual/Auto), `SUBSCRIPTION_NUMBER_OF_BILLING_CYCLES`, `SUBSCRIPTION_NUMBER_OF_FAILED_ATTEMPTS`, `SUBSCRIPTION_CANCELLATION_REASON_ID` (only when manually cancelled), `SUBSCRIPTION_FINISH_DATE` ("sent only in IPN type 11. SubscriptionFinished"), `IS_ON_TRIAL_PERIOD`, `TRIAL_PERIOD_TILL`, `TEST_MODE`, `IS_RESENT` ("passed only if webhook/IPN request is resent"), `INVOICE_LINK`, `PAYMENT_METHOD_ID/_NAME`.
Caveat: the doc does not explicitly say "ORDER_CUSTOM_FIELDS is included in every subscription event"; it is simply an unannotated general parameter. Verify once with the IPN simulator/test-mode order before relying on it for `SubscriptionSuspended` etc.

**Authenticity:**
- `SIGNATURE`: "The IPN verification signature hash is SHA256({ORDER_ID}+{ORDER_STATUS}+{ORDER_TOTAL_AMOUNT}+{CUSTOMER_EMAIL}+{VALIDATION_KEY}+{TEST_MODE}+{IPN_TYPE_NAME})" (concatenation, no literal "+"); validation key in Store Settings → General settings → Integration.
- `HASH`: "MD5("1") for test orders or MD5 (OrderId+SecretKey) in case of real orders."
- IP allowlist: IPv4 `198.199.123.239`, `157.230.8.40`; IPv6 `2604:a880:400:d0::1843:7001`, `2604:a880:400:d1::b6c:c001`.
Source for all of B1's IPN content: https://developers.payproglobal.com/docs/integrate-with-paypro-global/webhook-ipn/

### B2. Changing the IPN URL and resending IPNs

- Set/change: "Navigate to Store settings -> Product setup … Enter a URL in the IPN URL field. You may apply it to all products at ones." Multiple endpoints: "Store Settings -> General Settings -> Integration. In the IPN URLs field, enter one webhook URL per line." Wildcards allowed (`https://*.example.com/ipn/`); per-order routing via `&ipn-domain=ipn.example.com`.
- Replay: "navigate to Reports -> Others -> IPN to see the logs" and "Selecting the corresponding events and clicking on the Letter icon or Bulk actions -> Resend menu options, will create another attempt." Resent IPNs carry `IS_RESENT=1`.
- Retry policy: "we will retry the call to your webhook URL every 30 minutes for a maximum of 3 attempts. After the last failed attempt, we will send an email notification to the 'contact' email on record."
- Test tooling: IPN Simulator at https://cc.payproglobal.com/Tools/SimulateIpn "instantly sends extensive purchase details directly to the URL that you provided"; test orders via `&use-test-mode=true&secret-key=SECRETKEY`.
Sources: https://developers.payproglobal.com/docs/integrate-with-paypro-global/webhook-ipn/ , https://developers.payproglobal.com/docs/platform-overview/developer-tools/

### B3. Subscription Management API and export options

Endpoint list (all `POST https://store.payproglobal.com/api/...`, JSON body): Subscriptions — `GetList`, `GetSubscriptionDetails`, `ChangeName`, `ChangeQuantity`, `ChangeRecurringPrice`, `BulkChangeRecurringPrice`, `ChangeBillingPeriod`, `ChangeRenewalType`, `ChangeNextPaymentDate`, `ChangeTrialPeriodDate`, `Suspend`, `BulkSuspendSubscriptions`, `Terminate`, `BulkTerminateSubscriptions`, `Finish`, `BulkFinishSubscriptions`, `Renew`, `BulkRenewSubscriptions`, `ChangeMaxNumberOfBillingCycles`, `ChangeProduct`, `ApplyDiscount`, `ApplyAccumulativeDiscount`, `DoRecurringPayment`, `ChangeCustomFields`; Orders — `GetList`, `GetOrderDetails`, `DoReferenceCharge`, `DoRefund`, `DoPartialRefund`; Products — `GetProductPricing`, `GetStoreProducts`, `CreatePercentageDiscountCoupon`; Customers — `SendOnetimeLoginEmail`.
Source: https://developers.payproglobal.com/docs/api/overview/

- **`Subscriptions/GetList`** filters: `subscriptionIds[]`, `statusIds[]` ("1 – Active, 2 – Suspended, 3 – Terminated, 4 – Finished"), `customerEmail`, `dateFrom`/`dateTo`, `sortByDate`, `includeOrders`; paging `skip`/`take` ("Default - 50. Maximum - 100"). Response: id, name, status, createdAt, nextPayment, lastPayment, currentChargeCounter, subscriptionPrice, subscriptionCurrency, subscriptionPeriod, subscriptionPeriodValue, quantity, isTrial, renewalType, orders. **No filter by custom field; no custom fields and no customer email in the response.**
  Source: https://developers.payproglobal.com/docs/api/subscriptions/get-list/
- **`GetSubscriptionDetails`**: status, createdAt, changedAt, nextPayment, lastPayment, currentChargeCounter, subscriptionName/Price/Currency/Period, quantity, sku, productId, isTrial, renewalType, discountToBeApplied, affiliateAgreementId, orders. **Custom fields and customer email are not in the documented response.**
  Source: https://developers.payproglobal.com/docs/api/subscriptions/get-subscription-details/
- **`Orders/GetList`** filters: `orderIds[]`, `subscriptionId`, `customerEmail` ("Only domain in the format example.com can also be used"), status 1–5, `dateFrom`/`dateTo`, `includeTestOrders`; `take` max 100; response includes the customer billing email but custom fields are not documented in the list response.
  Source: https://developers.payproglobal.com/docs/api/orders/get-list/
- **`Orders/GetOrderDetails`** is the one call that returns everything you need: `customer {customerId, email, firstName, lastName}`, `customFields` (dictionary<string,string>), `orderItems[] {productId, orderItemName, quantity, billingPrice, sku, subscriptionId, subscriptionBillingCycle}`.
  Source: https://developers.payproglobal.com/docs/api/orders/get-order-details/
- **`Subscriptions/ChangeCustomFields`**: "Update the subscription custom fields." — `subscriptionId` + `customFields` dictionary; keys need not start with `x-`. Confirms subscription-level custom fields exist and are writable. Whether they are emitted in later rebill IPNs is not documented.
  Source: https://developers.payproglobal.com/docs/api/subscriptions/change-custom-fields/
- **`ChangeProduct`** (plan change / upgrade / downgrade): `subscriptionId`, `productId`, optional `quantity`, `startBillingImmediately`.
  Source: https://developers.payproglobal.com/docs/api/subscriptions/change-product/
- Suspend = "Suspend the subscription with the ability to renew it later"; Terminate = "without the ability to renew it later"; Renew = "renew previously suspended subscription".
  Source: https://developers.payproglobal.com/docs/subscriptions/subscription-management/
- **Dashboard export:** Reports section — "export all the data you are viewing, including any filters to a spreadsheet (.xlsx and .csv formats, also .PDF for Balance details report)"; a "Subscriptions" report exists, but the columns and whether custom fields are included are **not documented**. The "Subscription Migration" page is about importing subscriptions *into* PayPro from another provider (CSV with a `Customfields` column, card-based only), not an export.
  Sources: https://developers.payproglobal.com/docs/platform-overview/reporting-overview/ , https://developers.payproglobal.com/docs/integrate-with-paypro-global/subscription-migration-process-overview/
- No "GetSubscriptionsByCustomer" endpoint exists; `GetList` with `customerEmail` is the equivalent.

### B4. Customer portal

Portal: `https://cc.payproglobal.com/Customer/Account/Login`. Customers are identified by "the email address provided during checkout", logging in with email + password, or via a one-time link: `POST /api/Customers/SendOnetimeLoginEmail` with `customerEmail` ("required if orderId is not passed") or `orderId`; "the customer will receive an email with a one-time link to log in, valid for 15 minutes". Capabilities: order history with invoices, "Activate or cancel subscriptions", "Update the credit card assigned to a subscription", add/edit cards and set a backup card, manual "Pay Now", retrieve license keys.
Sources: https://developers.payproglobal.com/docs/customer-account/ , https://developers.payproglobal.com/docs/api/customers/send-one-time-login-email/

### B5. Stable identifiers for matching

- No first-class external customer id at checkout; `x-azure-user-id` is stored on the **order** (`ORDER_CUSTOM_FIELDS`, `CHECKOUT_QUERY_STRING`, `GetOrderDetails.customFields`).
- Every IPN carries `CUSTOMER_ID` (PayPro's integer id), `CUSTOMER_EMAIL`, `SUBSCRIPTION_ID`, `SUBSCRIPTION_INITIAL_ORDER_ID`. Email is mutable (IPN type 15 `OrderCustomerInformationChanged` fires when it changes), so treat `SUBSCRIPTION_ID`/`CUSTOMER_ID` as the durable keys and email/`x-azure-user-id` as lookup hints.
Sources: https://developers.payproglobal.com/docs/integrate-with-paypro-global/webhook-ipn/ , https://developers.payproglobal.com/docs/checkout-pages/custom-parameters/

### B6. Fees

Not published. Pricing page: "One fair price, all features included" / "You won't see a price tag" — quote-based. FAQ only lists payout costs (Payoneer $2, WebMoney 3.5%+$5, wire $21, ACH $3, PayPal free US/CA or 2% max $20 internationally) and "Payouts are processed on the 15th of every month." Third-party comparison sites put MoR fees generally at 4–8% but give no PayPro-specific figure — treat as unofficial.
Sources: https://payproglobal.com/pricing/ , https://payproglobal.com/faq/ , https://pricingnow.com/question/paypro-global-pricing/

### B7. API authentication and rate limits

Confirmed: "The communication method is POST"; `vendorAccountId` (Account settings → Business info) and `apiSecretKey` (Store settings → General settings → Integration; regenerable) go in the JSON body. Additionally: "API calls are verified by IP. Hence, to use API, you will need to send the list of your IP addresses to [support], and our team will whitelist them in the system." — a new backend on a new host needs its egress IPs allowlisted first. **Rate limits: not documented anywhere in the API reference** (grep of the overview page found no limit/throttle statements).
Source: https://developers.payproglobal.com/docs/api/overview/

---

## Implications for migration

**What a new backend can rebuild from PayPro alone (no B2C):**
1. Enumerate every subscription: `Subscriptions/GetList` with `statusIds=[1,2,3,4]`, `includeOrders=true`, paging `take=100`. This gives status, product, next/last payment, charge counter, renewal type — i.e. everything behind `WingmanSubscriptionPlan`, `PayProSubscriptionId`, `PayProSubscriptionEndDate` and `LastPayProSubscriptionPlan` (plan history = the orders' `productId` sequence).
2. For each subscription, call `Orders/GetOrderDetails` on the initial order (`orders[]` / `SUBSCRIPTION_INITIAL_ORDER_ID`) to get `customer.email`, `customer.customerId` and `customFields["x-azure-user-id"]` (old B2C objectId). That single call is the join key back to the exported B2C user list and to whatever id the new IdP assigns.
3. Keep the same IPN handler contract (form-encoded POST, SHA256 `SIGNATURE`), just point it at the new host via Store Settings → General Settings → Integration (or add a second URL line and cut over). Replay recent events from Reports → Others → IPN if the switch window loses anything; honour `IS_RESENT`.
4. Going forward, pass the **new** IdP user id as an `x-` field at checkout, and use `Subscriptions/ChangeCustomFields` to stamp the new id onto existing subscriptions so future lookups do not depend on the old B2C objectId.
5. Users still self-serve cards/cancellations in the PayPro portal (email-based), and the backend can hand out one-time login links via `SendOnetimeLoginEmail`.

**What is NOT possible / needs care:**
- `WingmanTermsConsentDateTime`, `PaddleUserId` and any other non-PayPro attribute exist only in B2C — export them via Graph (`$select` the extension names) before decommissioning; PayPro has no copy.
- Local-account **passwords cannot be exported** from B2C. Options: force password reset/magic-link in the new IdP, or run a lazy migration with a custom-policy REST call during sign-in (A4) for the period before cutover. Google/GitHub users carry over by `identities[].issuer` + `issuerAssignedId` with no password step.
- The 24-hour re-login will follow you to Entra External ID unchanged (and External ID removes B2C's ability to tune non-SPA refresh lifetimes). The fix is on the client side regardless of IdP: stop using a `spa` redirect URI in a desktop app and use a public-client/native flow, which the docs explicitly exempt from the 24 h limit.
- If the new IdP must be Entra External ID: GitHub sign-in is not on its supported-IdP list, and custom policies must be rewritten as custom authentication extensions with no parity guarantee.
- `Subscriptions/GetList` cannot filter by custom field or return custom fields; `GetSubscriptionDetails` returns neither customer email nor custom fields — always go through `Orders/GetOrderDetails`. Subscription-level custom fields set via `ChangeCustomFields` are not documented as appearing in rebill IPNs — verify with a test-mode order.
- Dashboard CSV export of subscriptions exists but its column set (and custom-field inclusion) is undocumented; plan on the API path.
- New backend egress IPs must be allowlisted by PayPro support before any API call works; no published rate limits, so budget conservatively.
- Per-MAU pricing for External ID above 50k and PayPro's percentage fee could not be retrieved from official pages.

Note: the session's WebSearch quota was exhausted near the end; the last two confirmations (GitHub absence on External ID's IdP page, password non-exportability) were done via direct fetch/grep of the official pages rather than search.