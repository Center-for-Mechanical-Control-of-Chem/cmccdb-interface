import os, sys

import numpy as np

dev_root = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
)))
root = os.path.join(dev_root, 'cmccdb_interface')
deps = os.path.join(dev_root, 'dependencies')
sys.path.insert(0, root)
sys.path.insert(0, deps)
# os.chdir(root)

import os.path
import unittest
import itertools
import pprint
import tempfile as tf
import cmccdb_interface.database.query as query

__all__ = [
    "CMCCDBTests"
]

class CMCCDBTests(unittest.TestCase):

    def test_Queries(self):

        frag = query.SchemaQueryFragment.from_path(['outcomes', 'reaction_time', 'value'], '<5')
        print(frag.to_sql())

        q = query.AdvancedSearchQuery.from_json(
            {"DatasetID": "any of [a, b, c]"}
        )
        for sql in q.to_query_components():
            print(sql.string)


if __name__ == '__main__':
    os.chdir(root)
    unittest.main('tests.CMCCDBTests')