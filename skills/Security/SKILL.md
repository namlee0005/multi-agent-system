## Security Analysis Rules

- Threat model first: enumerate assets, trust boundaries, and threat actors before recommending controls.
- OWASP Top 10 checklist applied to every API surface: injection, broken auth, IDOR, SSRF, misconfiguration.
- Auth/authz separation: authentication (who) and authorization (what) must be separate middleware layers.
- Secrets hygiene: no credentials in code, logs, or error messages. Vault or env-injected only.
- Least-privilege: every service account and API key scoped to minimum required permissions.
- Prioritize findings by CVSS likelihood × impact. Report top 3 critical risks with mitigations, not a laundry list.