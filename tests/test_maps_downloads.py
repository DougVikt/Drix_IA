"""Map download redirect/SSRF tests."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.maps import downloads


class FakeResponse:
    def __init__(self, status=200, location=None):
        self.status_code = status
        self.headers = {"location": location} if location else {}
        self.closed = False

    @property
    def is_redirect(self):
        return self.status_code in {301, 302, 303, 307, 308}

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def build_request(self, method, url, headers=None):
        return {"method": method, "url": url, "headers": headers or {}}

    def send(self, request, stream=True):
        self.requests.append(request["url"])
        return self.responses.pop(0)


class RedirectValidationTest(unittest.TestCase):
    def test_redirect_target_is_validated_before_request(self):
        redirect = FakeResponse(302, "https://private.example/file.pmtiles")
        client = FakeClient([redirect])
        seen = []

        def fake_validate(url, allow_private=False):
            seen.append((url, allow_private))
            if "private.example" in url:
                raise ValueError("host privado bloqueado")
            return url

        with mock.patch.object(downloads, "_validate_url", fake_validate):
            with self.assertRaises(ValueError):
                with downloads._stream_get(
                    client, "https://public.example/start.pmtiles", {}, False
                ):
                    pass

        self.assertEqual(client.requests, ["https://public.example/start.pmtiles"])
        self.assertTrue(redirect.closed)
        self.assertEqual(
            [url for url, _ in seen],
            [
                "https://public.example/start.pmtiles",
                "https://private.example/file.pmtiles",
            ],
        )

    def test_relative_redirect_is_followed_and_closed(self):
        redirect = FakeResponse(302, "/final.pmtiles")
        final = FakeResponse(200)
        client = FakeClient([redirect, final])

        with mock.patch.object(
            downloads, "_validate_url", lambda url, allow_private=False: url
        ):
            with downloads._stream_get(
                client,
                "https://maps.example/start.pmtiles",
                {"Range": "bytes=0-"},
                False,
            ) as response:
                self.assertIs(response, final)
                self.assertFalse(final.closed)

        self.assertTrue(redirect.closed)
        self.assertTrue(final.closed)
        self.assertEqual(
            client.requests,
            [
                "https://maps.example/start.pmtiles",
                "https://maps.example/final.pmtiles",
            ],
        )

    def test_too_many_redirects_raises(self):
        responses = [
            FakeResponse(302, f"/hop{i}.pmtiles")
            for i in range(downloads._MAX_REDIRECTS + 1)
        ]
        client = FakeClient(responses)

        with mock.patch.object(
            downloads, "_validate_url", lambda url, allow_private=False: url
        ):
            with self.assertRaises(RuntimeError):
                with downloads._stream_get(
                    client, "https://maps.example/start", {}, False
                ):
                    pass

        self.assertEqual(len(client.requests), downloads._MAX_REDIRECTS + 1)
        self.assertTrue(all(response.closed for response in responses))


if __name__ == "__main__":
    unittest.main(verbosity=2)
