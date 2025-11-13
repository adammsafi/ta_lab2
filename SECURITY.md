# Security Policy

## Supported versions

ta_lab2 is an early-stage research project. There are no formal LTS guarantees yet.  
In practice, the latest `main` branch and most recent tagged release receive attention.

## Reporting a vulnerability

If you believe you’ve found a security issue (for example, around:

- credential handling,
- database connection strings,
- cloud deployment configs,

please **do not** open a public GitHub issue at first.

Instead, email:

- **Primary contact:** your-email-here@example.com

Include:

- A clear description of the issue
- Steps to reproduce, if possible
- Any logs or stack traces that help

You’ll receive an acknowledgement as soon as reasonably possible.

## Public disclosure

Once an issue is confirmed and fixed, details can be added to the changelog or a dedicated security note.  
If something is sensitive (keys, secrets, etc.), it should never be committed to the repo; use `.env` files and `.gitignore`.
