#!/usr/bin/env python3
"""trade_journal.py 單元測試（使用臨時 DB）"""
import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import trade_journal as tj


class TestTradeJournal(unittest.TestCase):
    """交易日誌 CRUD + 統計測試"""

    @classmethod
    def setUpClass(cls):
        """使用臨時目錄避免污染正式 DB"""
        cls._tmp_dir = tempfile.mkdtemp()
        # Monkey-patch DB 路徑
        tj._DB_DIR = cls._tmp_dir
        tj._DB_PATH = os.path.join(cls._tmp_dir, "test_journal.db")

    def test_01_add_entry(self):
        """新增進場記錄"""
        tid = tj.add_entry(
            stock_id="2330", entry_date="2025-01-10",
            entry_price=600, shares=1000, name="台積電",
            strategy="balanced", entry_score=7.5,
            entry_reason="技術面突破",
        )
        self.assertIsInstance(tid, int)
        self.assertGreater(tid, 0)

    def test_02_get_open_trades(self):
        """查詢持倉中交易"""
        trades = tj.get_all_trades(open_only=True)
        self.assertGreater(len(trades), 0)
        self.assertEqual(trades[0]["stock_id"], "2330")
        self.assertEqual(trades[0]["is_open"], 1)

    def test_03_close_trade(self):
        """結算交易並檢查損益"""
        trades = tj.get_all_trades(open_only=True)
        tid = trades[0]["id"]

        result = tj.close_trade(tid, "2025-02-10", 660, "停利", is_us=False)
        self.assertNotIn("error", result)
        self.assertGreater(result["pnl"], 0)
        self.assertGreater(result["pnl_pct"], 0)

    def test_04_closed_shows_in_all(self):
        """已結算的交易出現在所有記錄，不在持倉"""
        all_trades = tj.get_all_trades(open_only=False)
        open_trades = tj.get_all_trades(open_only=True)
        self.assertGreater(len(all_trades), len(open_trades))

    def test_05_monthly_stats(self):
        """月度統計"""
        stats = tj.get_monthly_stats()
        self.assertGreater(stats["trade_count"], 0)
        self.assertGreater(stats["win_rate"], 0)
        self.assertGreater(stats["total_pnl"], 0)

    def test_06_add_multiple_and_stats(self):
        """多筆交易後的統計"""
        # 新增一筆虧損交易
        tid2 = tj.add_entry("2454", "2025-03-01", 1200, 500, "聯發科", "short")
        tj.close_trade(tid2, "2025-03-10", 1100, "停損")

        stats = tj.get_monthly_stats()
        self.assertEqual(stats["trade_count"], 2)
        self.assertEqual(stats["win_count"], 1)
        self.assertEqual(stats["loss_count"], 1)
        self.assertAlmostEqual(stats["win_rate"], 50.0)

    def test_07_us_stock_no_fee(self):
        """美股零費用"""
        tid = tj.add_entry("NVDA", "2025-01-15", 140, 100, "NVIDIA", "balanced")
        result = tj.close_trade(tid, "2025-02-15", 150, "停利", is_us=True)
        # 無費用：(150-140)*100 = 1000
        self.assertEqual(result["pnl"], 1000)

    def test_08_monthly_breakdown(self):
        """月度分解"""
        breakdown = tj.get_monthly_breakdown()
        self.assertIsInstance(breakdown, list)
        self.assertGreater(len(breakdown), 0)
        for item in breakdown:
            self.assertIn("year_month", item)
            self.assertIn("trade_count", item)

    def test_09_trades_df(self):
        """DataFrame 輸出"""
        df = tj.get_trades_df()
        self.assertFalse(df.empty)
        self.assertIn("stock_id", df.columns)
        self.assertIn("pnl_pct", df.columns)

    def test_10_delete_trade(self):
        """刪除記錄"""
        all_before = tj.get_all_trades()
        count_before = len(all_before)
        if count_before > 0:
            tj.delete_trade(all_before[0]["id"])
            all_after = tj.get_all_trades()
            self.assertEqual(len(all_after), count_before - 1)

    def test_11_alpha_no_benchmark(self):
        """Alpha 計算（無大盤資料）"""
        alpha = tj.calc_alpha(benchmark_fetcher=None)
        self.assertFalse(alpha["has_benchmark"])

    @classmethod
    def tearDownClass(cls):
        """清理臨時 DB"""
        try:
            os.remove(tj._DB_PATH)
            os.rmdir(cls._tmp_dir)
        except Exception:
            pass


class TestConsensusScore(unittest.TestCase):
    """scoring.py consensus score 測試"""

    def test_strong_bullish(self):
        """全面多頭 → strong bullish"""
        from scoring import calc_consensus_score
        r = calc_consensus_score(8, 7, 7, 8)
        self.assertEqual(r["direction"], "bullish")
        self.assertEqual(r["signal_strength"], "strong")
        self.assertEqual(r["consensus_score"], 100)

    def test_strong_bearish(self):
        """全面空頭 → strong bearish"""
        from scoring import calc_consensus_score
        r = calc_consensus_score(2, 3, 2, 3)
        self.assertEqual(r["direction"], "bearish")
        self.assertEqual(r["signal_strength"], "strong")

    def test_mixed_signals(self):
        """多空分歧"""
        from scoring import calc_consensus_score
        r = calc_consensus_score(8, 2, 7, 3)
        self.assertEqual(r["direction"], "mixed")
        self.assertLessEqual(r["consensus_score"], 50)

    def test_no_data(self):
        """無資料"""
        from scoring import calc_consensus_score
        r = calc_consensus_score(0, 0, 0, 0)
        self.assertEqual(r["consensus_score"], 50)
        self.assertEqual(r["signal_strength"], "weak")


if __name__ == "__main__":
    unittest.main()
