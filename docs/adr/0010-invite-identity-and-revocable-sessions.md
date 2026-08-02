# ADR 0010: Invite identity and revocable sessions

- Status: Accepted and implemented
- Date: 2026-08-02

## Context

AniOS already scoped durable records by `user_id`, but trusted-local browser
state could select that identifier and expiring signed bearer tokens had no
password account or revocation lifecycle. Sharing the UI with invited users
requires the server to derive one owner and prevent a login-name change from
orphaning chats, memory, presentations, or artifacts.

## Decision

Use an invited account boundary. Each account has an immutable stable
`user_id` for data ownership and an independently unique normalized login name.
Passwords use Argon2id. Browser login issues a random opaque token in a
host-only HttpOnly cookie and persists only its SHA-256 digest with expiry and
revocation state. Logout, password replacement, and account disable revoke
sessions. Unsafe cookie-authenticated requests require an allowlisted Origin.

The operator can create an account through a non-echoing password prompt or
mint an expiring one-time registration code whose SHA-256 digest is stored.
Browser registration locks and consumes that invitation while creating the
account and first session in one transaction. There is no unrestricted public
signup or destructive account-delete command. Legacy signed bearer tokens
remain for bounded automation and scoped tests, while trusted-local
auth-disabled mode remains an explicit single-user development option.

## Consequences

- A login such as `admin` can authorize stable owner `ani.mallya`; the login
  identifier is not used as a foreign key for owned data.
- Browser local storage cannot choose the active user. All private API calls use
  the authenticated subject and existing ownership checks.
- Session rows can be invalidated without deleting user data.
- HTTPS deployments must enable Secure cookies and same-origin or explicitly
  trusted ingress. Shared Redis attempt limits are implemented; recovery, MFA,
  public administration, and per-user encryption keys remain separate planned
  controls.
