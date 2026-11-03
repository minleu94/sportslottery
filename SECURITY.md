# Security Policy

## System and scope

Sportslottery is a local sports-market research and simulated ticket-tracking
application. The repository includes a Streamlit desktop UI, an optional
FastAPI/React interface, SQLite-backed profiles and ledgers, scheduled market
collection, and an optional LINE webhook. Deployments may be loopback-only or
explicitly exposed on a local network or through a tunnel. Treat any reachable
network endpoint as attacker-accessible.

Security-sensitive assets include profile credentials, session tokens, wallet
and ticket records, private research data, API keys, and LINE channel secrets.

## Threat model and trust boundaries

- Network requests, browser input, profile identifiers, uploaded/request
  payloads, webhook events, and market-provider responses are untrusted.
- A display name is not an identity or authorization role. Profile ID and
  server-validated session state determine access.
- Forwarded client-address headers are trusted only from configured proxy
  peers. CORS origins must be explicit; cookie-authenticated mutations require
  a trusted request origin.
- LINE callbacks are untrusted until their signature is verified.
- Remote access must fail closed when the administrator credential is missing,
  malformed, or still set to its default.

## Security invariants

- Users can read or mutate only their own profile, wallet, tickets, and private
  records unless an authenticated administrator action explicitly permits it.
- Administrator access is bound to the fixed administrator profile, never a
  user-controlled name or request field.
- PINs are stored as salted password hashes. Session tokens and provider
  secrets must not appear in API responses, browser persistent storage, logs,
  fixtures, or committed local configuration.
- Authentication attempts, request bodies, profile growth, and webhook event
  batches remain bounded. State-changing cookie requests are protected against
  cross-site request forgery.
- Process launchers may stop only processes they own or have verified as the
  application's exact service instance.

## Reportable findings

Report reachable authentication or authorization bypasses, cross-profile data
access, credential or session disclosure, CSRF/CORS bypass, unsafe proxy trust,
webhook signature bypass, request-driven code execution, meaningful
resource-exhaustion paths, or corruption/loss of wallet and research records.
Severity should reflect realistic reachability and impact; remotely reachable
unauthenticated access to another user's data or administrative operations is
high priority.

## Out of scope and limitations

Prediction quality, betting profitability, and ordinary market-data accuracy
are product/research concerns unless they expose a security boundary or cause
unauthorized financial or personal-data access. CI and offline tests do not
prove live deployment safety, tunnel behavior, or backup recoverability.
In-memory rate-limit state resets when the service restarts; assess this as a
defense-in-depth limitation, not as a substitute for authorization.

## Reporting

Do not publish credentials, personal data, or an unpatched exploit in a public
issue. Use GitHub private vulnerability reporting for this repository if it is
available; otherwise contact the repository maintainer privately through
GitHub. No response-time commitment is currently published.
