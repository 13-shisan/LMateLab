import unittest

from services.competition_agent.literature import search_openalex


class _Response:
    def __init__(self, body=None, *, failed=False):
        self.body = body
        self.failed = failed

    def raise_for_status(self):
        if self.failed:
            raise RuntimeError("upstream unavailable")

    def json(self):
        return self.body


class _FallbackClient:
    def __init__(self):
        self.requests = []

    def get(self, url, *, params):
        self.requests.append((url, params))
        if "openalex.org" in url:
            return _Response(failed=True)
        return _Response({
            "message": {
                "items": [{
                    "DOI": "10.1000/mos2",
                    "title": ["Band structure of MoS2"],
                    "abstract": "<jats:p>Electronic band dispersion.</jats:p>",
                    "author": [{"given": "A.", "family": "Researcher"}],
                    "published-online": {"date-parts": [[2025, 4, 1]]},
                    "URL": "https://doi.org/10.1000/mos2",
                }],
            },
        })


class CompetitionAgentLiteratureTests(unittest.TestCase):
    def test_crossref_is_used_when_openalex_is_unavailable(self):
        client = _FallbackClient()

        items = search_openalex("MoS2 band structure", 5, client=client)

        self.assertEqual(2, len(client.requests))
        self.assertIn("api.openalex.org", client.requests[0][0])
        self.assertIn("api.crossref.org", client.requests[1][0])
        self.assertEqual("Crossref", items[0]["source"])
        self.assertEqual("Band structure of MoS2", items[0]["title"])
        self.assertEqual(["A. Researcher"], items[0]["authors"])
        self.assertEqual(2025, items[0]["year"])
        self.assertEqual("Electronic band dispersion.", items[0]["abstract"])
        self.assertEqual("https://doi.org/10.1000/mos2", items[0]["url"])


if __name__ == "__main__":
    unittest.main()
