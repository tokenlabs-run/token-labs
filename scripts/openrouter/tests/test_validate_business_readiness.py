import copy
import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).parents[1] / "validate_business_readiness.py"
SPEC = importlib.util.spec_from_file_location("validate_business_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def complete_document():
    return {
        "schema_version": 1,
        "legal_entity": {key: "verified" for key in MODULE.REQUIRED_TEXT["legal_entity"]},
        "authority": {key: "verified" for key in MODULE.REQUIRED_TEXT["authority"]},
        "tax_and_banking": {"payout_currency": "USD", "evidence_reference": "vault:tax", "tax_registration_confirmed": True, "business_bank_account_confirmed": True},
        "domain": {"primary_domain": "tokenlabs.run", "website_url": "https://www.tokenlabs.run", "provider_contact": "providers@tokenlabs.run", "legal_contact": "legal@tokenlabs.run", "privacy_contact": "privacy@tokenlabs.run", "evidence_reference": "vault:domain", "domain_control_confirmed": True, "mailboxes_monitored_confirmed": True, "dns_tls_email_auth_confirmed": True},
        "policies": {"privacy_policy_url": "https://www.tokenlabs.run/privacy.html", "terms_url": "https://www.tokenlabs.run/terms.html", "data_policy_url": "https://www.tokenlabs.run/data-policy.html", "approval_evidence_reference": "vault:policy", "legal_review_confirmed": True, "operational_controls_confirmed": True},
        "openrouter": {"display_name": "Token Labs", "desired_slug": "token-labs", "hq_location": "verified location", "inference_location": "verified location", "approval_evidence_reference": "vault:approval", "commercial_terms_approved": True, "application_submission_approved": True},
    }


class ValidateBusinessReadinessTests(unittest.TestCase):
    def test_complete_manifest_passes(self):
        self.assertEqual([], MODULE.validate(complete_document()))

    def test_template_is_safely_incomplete(self):
        template = Path(__file__).parents[3] / "docs/openrouter/business-readiness.template.json"
        self.assertGreater(len(MODULE.validate(json.loads(template.read_text()))), 20)

    def test_rejects_external_contact_and_policy_hosts(self):
        document = copy.deepcopy(complete_document())
        document["domain"]["legal_contact"] = "legal@example.com"
        document["policies"]["terms_url"] = "https://example.com/terms"
        errors = MODULE.validate(document)
        self.assertIn("domain.legal_contact must use the verified primary domain", errors)
        self.assertIn("policies.terms_url must be HTTPS on the verified primary domain", errors)

    def test_accepts_an_owner_selected_primary_domain(self):
        document = complete_document()
        document["domain"].update({"primary_domain": "tokenlabs.co", "website_url": "https://www.tokenlabs.co", "provider_contact": "providers@tokenlabs.co", "legal_contact": "legal@tokenlabs.co", "privacy_contact": "privacy@tokenlabs.co"})
        document["policies"].update({"privacy_policy_url": "https://www.tokenlabs.co/privacy.html", "terms_url": "https://www.tokenlabs.co/terms.html", "data_policy_url": "https://www.tokenlabs.co/data-policy.html"})
        self.assertEqual([], MODULE.validate(document))

    def test_rejects_malformed_primary_domain(self):
        document = complete_document()
        document["domain"]["primary_domain"] = "https://tokenlabs.run/path"
        self.assertIn("domain.primary_domain must be a bare DNS domain", MODULE.validate(document))

    def test_rejects_placeholder_text(self):
        document = complete_document()
        document["legal_entity"]["registered_name"] = "TBD"
        self.assertIn("legal_entity.registered_name contains a placeholder", MODULE.validate(document))


if __name__ == "__main__":
    unittest.main()
