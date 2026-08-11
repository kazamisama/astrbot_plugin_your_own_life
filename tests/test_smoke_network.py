"""Optional real-network smoke test. Run with LIFE_SMOKE_NET=1."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from life.fetchers import USER_AGENT, fetch_github, fetch_hn


@unittest.skipUnless(os.environ.get("LIFE_SMOKE_NET") == "1", "set LIFE_SMOKE_NET=1 to enable")
class NetworkSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_hn_and_github_reachable(self):
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
            hn = await fetch_hn(client, "astrbot", hits=3)
            gh = await fetch_github(client, "astrbot stars:>5", per_page=3)
        self.assertGreater(len(hn), 0)
        self.assertGreater(len(gh), 0)


if __name__ == "__main__":
    unittest.main()