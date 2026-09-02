# OpenRouter business readiness

This checklist covers the human and organizational work needed before Token
Labs can contract with or submit a provider application to OpenRouter. It does
not establish a company, authorize a filing, approve policies, or authorize an
application submission.

## Safe workflow

1. Copy `business-readiness.template.json` to a private working location. A
   completed manifest may contain sensitive identifiers and addresses and must
   not be committed to this public repository.
2. Replace `null` values only from documentary evidence. Use an internal
   evidence reference (for example, a vault record ID), never a tax identifier,
   bank detail, identity document, or home address in Git.
3. Have an authorized representative confirm the entity, authority, commercial,
   policy, domain, location, and submission fields.
4. Validate the working copy:

   ```shell
   python3 scripts/openrouter/validate_business_readiness.py /secure/path/business-readiness.json
   ```

5. Transfer only approved application fields into
   `docs/OPENROUTER_APPLICATION_DRAFT.md`. Submission remains a deliberate human
   action. During preparation, `--allow-incomplete` lists blockers without
   returning an error.

## Required evidence and decisions

| Area | Required confirmation | Keep out of Git |
|---|---|---|
| Formation | Registered legal name, entity type, jurisdiction, registration number, formation date, registered address | Formation documents, personal addresses, identity documents |
| Authority | Representative name/title and evidence they may accept provider terms | Signatures, identity documents, board consents |
| Tax and payouts | Tax registration, business bank account, payout currency | Tax numbers, bank/routing/account numbers |
| Domain and contacts | Control of `tokenlabs.run`; monitored provider, legal, and privacy mailboxes on that domain | Mailbox credentials and DNS-provider secrets |
| Policies | Legal approval of privacy, terms, and data-policy drafts; operational confirmation that published claims are true | Privileged legal advice and internal security evidence |
| OpenRouter | HQ and inference locations, commercial approval, explicit submission approval | Contracts and negotiation records |

Public policy drafts live at `docs/privacy.html`, `docs/terms.html`, and
`docs/data-policy.html`. They intentionally retain launch warnings until their
mailboxes, controls, legal entity, and approvals are verified.

## Stop conditions

Do not submit when the validator reports blockers, a policy claim has not been
confirmed against production behavior, an address or identifier was inferred,
or the representative lacks explicit authority. Domain ownership, mailbox
delivery, and public policy URLs must be tested by an authorized human.
