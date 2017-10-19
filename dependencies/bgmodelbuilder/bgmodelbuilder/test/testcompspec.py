import unittest
import json

from .. import compspec
from ..compspec import units

class TestCompSpec(unittest.TestCase):
    def setUp(self):
        """Build some simple specs"""
        self.radio = compspec.RadioactiveContam("U238", rate="10*Bq/kg")
        self.radio1 = compspec.RadioactiveContam("Th232", rate="15*Bq/kg")
        self.combo = compspec.CombinedSpec("combo",
                                           subspecs=[self.radio, self.radio1])
        self.radon = compspec.RadonExposure(radonlevel="130 Bq/m^3",
                                            exposure="300 days")
        self.cosmotopes = [compspec.CosmogenicIsotope(name='Co60', 
                                             activationrate="30/kg/day",
                                             halflife="100 year"),
                           {'name':'Mn54', 'activationrate':"3/kg/day",
                            'halflife':'1 year'},
                           ]
        self.cosmo = compspec.CosmogenicActivation(isotopes=self.cosmotopes,
                                                   exposure="200 days")
        self.specs = [self.radio, self.combo, self.radon, self.cosmo]

    def testExport(self):
        """Ensure that we can cast to and from pure dicts"""
        self.maxDiff = None
        for spec in self.specs:
            export = spec.todict()
            self.assertIsInstance(export, dict)
            string = json.dumps(export)
            self.assertIsInstance(string, str)
            clone = compspec.buildspecfromdict(export)
            self.assertIs(type(spec), type(clone))
            self.assertEqual(spec.todict(), clone.todict())
            self.assertEqual(spec.rate, clone.rate)

    def testRadioVal(self):
        """Test that a plain radiogenic retains the right units"""
        self.assertEqual(self.radio.rate, 10*units['Bq/kg'])
    
    def testCombinedSpec(self):
        """Test that a combined spec gets the correct total rate"""
        self.assertEqual(self.combo.rate,25*units['Bq/kg'])
        

if __name__ == "__main__":
    unittest.main()

