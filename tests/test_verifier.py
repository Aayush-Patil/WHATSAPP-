import unittest

from app.schemas import Evidence
from app.verifier import Scores, decide_verdict, rank_evidence
from app.providers import fallback_claims


class VerdictMappingTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [Evidence(id="s1", title="Official source", url="https://example.org", publisher="example.org", excerpt="The program is open to residents.", trusted=True)]

    def test_supported_claim(self):
        self.assertEqual(decide_verdict([Scores(0.91, 0.03, 0.06)], self.evidence), ("verified", None))

    def test_contradicted_claim(self):
        self.assertEqual(decide_verdict([Scores(0.02, 0.94, 0.04)], self.evidence), ("false", None))

    def test_partly_supported_claim(self):
        verdict, reason = decide_verdict([Scores(0.56, 0.12, 0.32)], self.evidence)
        self.assertEqual(verdict, "partly_supported")
        self.assertEqual(reason, "evidence_support_is_incomplete")

    def test_conflicting_evidence_is_not_called_true_or_false(self):
        verdict, reason = decide_verdict([Scores(0.83, 0.82, 0.35)], self.evidence)
        self.assertEqual((verdict, reason), ("cannot_confirm", "conflicting_sources"))

    def test_explicitly_superseded_evidence_is_outdated(self):
        evidence = [Evidence(id="s1", title="Notice", url="https://example.org", publisher="example.org", excerpt="This program was superseded by a new policy.", trusted=True)]
        self.assertEqual(decide_verdict([Scores(0.62, 0.04, 0.34)], evidence), ("outdated", "source_explicitly_marks_information_out_of_date"))

    def test_missing_evidence_cannot_confirm(self):
        self.assertEqual(decide_verdict([], []), ("cannot_confirm", "no_usable_evidence"))


class ClaimExtractionTests(unittest.TestCase):
    def test_sentence_fallback_returns_claim_sized_units(self):
        text = "This is a forwarded message with enough detail to count as one factual statement. A second claim has sufficient detail for checking too."
        claims = fallback_claims(text)
        self.assertEqual(len(claims), 2)
        self.assertIn("one factual statement", claims[0])

    def test_retrieval_prefers_text_with_claim_terms(self):
        other = Evidence(id="s2", title="Weather report", url="https://example.org/weather", publisher="example.org", excerpt="Tomorrow will be sunny.")
        ranked = rank_evidence("The public health program gives residents a vaccine", [other, self.evidence_for_health()])
        self.assertEqual(ranked[0].id, "s3")

    @staticmethod
    def evidence_for_health():
        return Evidence(id="s3", title="Public health program", url="https://example.org/health", publisher="example.org", excerpt="Residents can receive a vaccine through the public health program.", trusted=True)

    def test_untrusted_user_url_cannot_change_verdict(self):
        untrusted = [Evidence(id="u1", title="Anonymous post", url="https://example.org", publisher="example.org", excerpt="The program is open to residents.")]
        self.assertEqual(decide_verdict([Scores(0.99, 0.0, 0.01)], untrusted), ("cannot_confirm", "no_usable_evidence"))


if __name__ == "__main__":
    unittest.main()
