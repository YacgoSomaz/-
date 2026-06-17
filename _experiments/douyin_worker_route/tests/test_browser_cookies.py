import unittest
from unittest.mock import patch

from pipeline import browser_cookies


class BrowserCookieTests(unittest.TestCase):
    def setUp(self) -> None:
        browser_cookies._jar = {"ttwid": "old"}
        browser_cookies._minted_at = 100
        browser_cookies._mint_rid = None
        browser_cookies._last_auto_attempt = 0

    def test_manual_remint_replaces_cookie_even_when_recent(self) -> None:
        with (
            patch.object(browser_cookies, "_mint", return_value={"ttwid": "new", "odin_tt": "ok"}),
            patch.object(browser_cookies, "_save_cache") as save,
            patch.object(browser_cookies.time, "time", return_value=200),
        ):
            result = browser_cookies.remint("123")

        self.assertTrue(result["ok"])
        self.assertEqual(browser_cookies._jar["ttwid"], "new")
        self.assertEqual(browser_cookies._mint_rid, "123")
        save.assert_called_once()

    def test_manual_remint_keeps_old_cookie_on_failure(self) -> None:
        with patch.object(browser_cookies, "_mint", return_value={}):
            result = browser_cookies.remint("123")

        self.assertFalse(result["ok"])
        self.assertEqual(browser_cookies._jar, {"ttwid": "old"})

    def test_cached_jar_never_opens_browser_even_when_expired(self) -> None:
        with (
            patch.object(browser_cookies, "_mint") as mint,
            patch.object(browser_cookies.time, "time", return_value=100 + 9 * 3600),
        ):
            jar = browser_cookies.cached_jar()

        self.assertEqual(jar, {"ttwid": "old"})
        mint.assert_not_called()

    def test_auto_refresh_mints_once_when_cookie_is_expired(self) -> None:
        with (
            patch.object(browser_cookies, "_mint", return_value={"ttwid": "new", "odin_tt": "ok"}) as mint,
            patch.object(browser_cookies, "_save_cache"),
            patch.object(browser_cookies.time, "time", return_value=100 + 9 * 3600),
        ):
            result = browser_cookies.auto_refresh("123")

        self.assertTrue(result["ok"])
        self.assertTrue(result["attempted"])
        self.assertEqual(browser_cookies._jar["ttwid"], "new")
        mint.assert_called_once_with("123")

    def test_failed_auto_refresh_does_not_reopen_browser_during_cooldown(self) -> None:
        browser_cookies._jar = {}
        with (
            patch.object(browser_cookies, "_load_cache", return_value=({}, 0)),
            patch.object(browser_cookies, "_mint", return_value={}) as mint,
            patch.object(browser_cookies.time, "time", side_effect=[1000, 1001]),
        ):
            first = browser_cookies.auto_refresh("123")
            second = browser_cookies.auto_refresh("123")

        self.assertFalse(first["ok"])
        self.assertTrue(first["attempted"])
        self.assertFalse(second["attempted"])
        mint.assert_called_once_with("123")


if __name__ == "__main__":
    unittest.main()
