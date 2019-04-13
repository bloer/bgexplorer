import unittest
import json

from ..component import Component, Assembly
from ..emissionspec import RadioactiveContam
from ..bgmodel import BgModel
from ..common import units

class TestComponent(unittest.TestCase):
    """Unit tests for component definitions"""
    def setUp(self):
        """Build a very simple model"""

        self.assembly = Assembly("Test Assembly", components=[
            (Component("screw", material="brass", mass=1*units.g, specs=[
                RadioactiveContam("U238",  "10 mBq/kg"),
                RadioactiveContam("Th232", "20 mBq/kg"),
                RadioactiveContam("K40",   "30 mBq/kg")]), 8),
            (Assembly("widget", components=[
                (Component("gear", material="steel", mass=1*units.kg, specs=[
                    RadioactiveContam("Co60","2 Bq/kg")]), 3),
                (Assembly("circuit board", components=[
                    Component("PCB", material="cirlex", mass=10*units.g, specs=[
                        RadioactiveContam("U238", "3 mBq/kg"),
                        RadioactiveContam("K40", "150 mBq/kg")]),
                    Component("resistor", specs=[
                        RadioactiveContam("Th232","100 mBq", normfunc="piece")])
                ]), 2)
            ]), 5),
        ])
        self.model = BgModel("Test Model", self.assembly)


    def testSpecRegistry(self):
        self.assertEqual(len(self.model.specs), 7)

    def testCompRegistry(self):
        self.assertEqual(len(self.model.components), 7)

    def testExport(self):
        self.maxDiff = None
        export = self.model.todict()
        self.assertIsInstance(export, dict)
        self.assertIsInstance(json.dumps(export), str)
        clone = BgModel.buildfromdict(export)
        #buildfromdict modifies the dictionary!
        self.assertEqual(self.model.todict(), clone.todict())
        
    

if __name__ == "__main__":
    unittest.main()
