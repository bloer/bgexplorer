import unittest
import json

from ..component import units, Component, Assembly, buildcomponentfromdict

class TestComponent(unittest.TestCase):
    """Unit tests for component definitions"""
    def setUp(self):
        """Build a very simple assembly"""
        self.screw = Component('screw', material='brass', mass=10*units.g)
        self.plate = Component('plate', material='copper', mass='10*kg',
                               surface='50 cm^2')
        self.fixture = Assembly('fixture', components=[self.plate, 
                                                       (self.screw,10) ])
        self.detector = Assembly('detector', components=[(self.fixture, 10)])

    def testTotalWeight(self):
        self.assertEqual(self.screw.gettotalweight(), 100)

    def testTotalMass(self):
        self.assertEqual(self.detector.mass, 101*units.kg)
     
    def testExport(self):
        self.maxDiff = None
        export = self.plate.todict()
        clone = buildcomponentfromdict(export)
        self.assertEqual(self.plate.mass, clone.mass)
        self.assertEqual(self.plate.todict(), clone.todict())

if __name__ == "__main__":
    unittest.main()
