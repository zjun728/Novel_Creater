import hashlib
import json
from pathlib import Path
import unittest

from backend.control_plane.restricted_jcs import (
    JCSCanonicalizationError,
    canonical_sha256,
    canonicalize,
    loads_rejecting_duplicates,
)


VECTORS = (
    Path(__file__).parents[3]
    / "tools"
    / "control-plane-qa"
    / "fixtures"
    / "rfc8785-restricted-vectors.json"
)


class RestrictedJCSTest(unittest.TestCase):
    def test_checked_in_valid_vectors(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        for case in vectors["valid"]:
            with self.subTest(case["name"]):
                result = canonicalize(case["value"])
                self.assertEqual(result.decode("utf-8"), case["canonical"])
                self.assertEqual(
                    canonical_sha256(case["value"]),
                    hashlib.sha256(result).hexdigest(),
                )

    def test_duplicate_keys_are_rejected_at_every_depth(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        for case in vectors["invalidRaw"]:
            with self.subTest(case["name"]):
                with self.assertRaises(JCSCanonicalizationError):
                    loads_rejecting_duplicates(case["raw"].encode("utf-8"))

    def test_invalid_utf8_is_rejected(self):
        with self.assertRaises(JCSCanonicalizationError):
            loads_rejecting_duplicates(b'{"value":"\xff"}')

    def test_rejects_values_outside_restricted_profile(self):
        invalid = [None, True, False, 1.0, 9007199254740992, -9007199254740992]
        for value in invalid:
            with self.subTest(repr(value)):
                with self.assertRaises(JCSCanonicalizationError):
                    canonicalize(value)

    def test_rejects_unpaired_surrogates_in_keys_and_values(self):
        for value in ["\ud800", {"\udfff": "x"}, {"x": "\ud800"}]:
            with self.subTest(repr(value)):
                with self.assertRaises(JCSCanonicalizationError):
                    canonicalize(value)

    def test_rejects_non_string_object_keys(self):
        with self.assertRaises(JCSCanonicalizationError):
            canonicalize({1: "value"})

    def test_rejects_cyclic_containers_with_the_public_error(self):
        cyclic_list = []
        cyclic_list.append(cyclic_list)
        cyclic_dict = {}
        cyclic_dict["self"] = cyclic_dict
        for value in [cyclic_list, cyclic_dict]:
            with self.subTest(type(value).__name__):
                with self.assertRaises(JCSCanonicalizationError):
                    canonicalize(value)


if __name__ == "__main__":
    unittest.main()
