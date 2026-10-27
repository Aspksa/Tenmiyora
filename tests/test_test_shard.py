"""The parallel CI runner must neither skip nor repeat any unittest."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bootstrap"))
from test_shard import discover, select_cases


class TestSharding(unittest.TestCase):
    def test_four_shards_partition_all_test_methods(self):
        all_tests=discover()
        ids=[test.id() for test in all_tests]
        self.assertEqual(len(ids),len(set(ids)))
        partitions=[select_cases(all_tests,i,4) for i in range(4)]
        observed=[test.id() for part in partitions for test in part]
        self.assertEqual(sorted(observed),sorted(ids))
        self.assertTrue(all(part for part in partitions))

    def test_invalid_shards_are_rejected(self):
        for shard,total in [(-1,4),(4,4),(0,0),(1,1)]:
            with self.subTest(shard=shard,total=total):
                with self.assertRaises(ValueError):
                    select_cases([],shard,total)


if __name__=="__main__":
    unittest.main()
