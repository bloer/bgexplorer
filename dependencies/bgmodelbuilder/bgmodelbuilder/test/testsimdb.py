import unittest

from ..component import Component, Assembly
from ..emissionspec import RadioactiveContam, CombinedSpec
from ..bgmodel import BgModel
from ..common import units
from ..simulationsdb import SimulationsDB, SimDataMatch


class TestingSimulationsDB(SimulationsDB):
    """Toy simulations database used for testing purposes"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.baserates = dict(U238=4, Th232=3, Co60=2, K40=1)

    def genqueries(self, request, findnewdata=True):
        result = [request]
        #We only know a few things
        request.query = "FIND "+request.spec.name
        
        if request.spec.name in self.baserates:
            #Add 1e7 gammas for all 
            dataset = (request.spec.name, "gamma")
            request.livetime = (self.getprimaries(None)/request.emissionrate)
            request.dataset = dataset
            
            if dataset[0] in ('U238', 'Th232'):
                query = request.query + " neutron"
                dataset = (request.spec.name, "neutron")
                weight = 1.e-6
                livetime = request.livetime / weight
                result.append(request.clone(query, weight, dataset, livetime))
        
        return result
            
    def evaluate(self, values, matches):
        #we know how to evaluate "primaries" and "rate"
        result = dict()
        if "primaries" in values:
            result["primaries"] = sum(getprimaries(match) for match in matches
                                      if match.dataset)
        if "rate" in values:
            result["rate"] = sum(self.gethits(match)/match.livetime 
                                 for match in matches if match.dataset)
        if "gammarate" in values:
            result["gammarate"] = sum(self.gethits(match)/match.livetime 
                                      for match in matches 
                                      if match.dataset 
                                      and match.dataset[1]=="gamma")
        if "neutronrate" in values:
            result["neutronrate"] = sum(self.gethits(match)/match.livetime 
                                      for match in matches 
                                      if match.dataset 
                                      and match.dataset[1]=="neutron")
        return result
        

    def getprimaries(self, match):
        return 1.e7
        
    def gethits(self, match):
        base = 100 * self.baserates[match.dataset[0]]
        if match.dataset[1] == "neutron":
            base /= 1e5
        return base 



class TestSimsDB(unittest.TestCase):
    """Test whether the interface for matching simulation data to components
    works.
    """
    
    def setUp(self):
        specs1 = CombinedSpec(_id="S1", subspecs=[
            RadioactiveContam("U238", rate="1 mBq/kg", _id="U1"),
            RadioactiveContam("Th232", rate="2 mBq/kg", _id="T1"),
            RadioactiveContam("K40", rate="3 mBq/kg", _id="K1"),
            RadioactiveContam("Co60", rate="4 mBq/kg", _id="Co1"),
        ])
        specs2 = CombinedSpec(_id="S2", subspecs=[
            RadioactiveContam("K40", rate="100 mBq/kg", _id="K2"),
            RadioactiveContam("Ac197", rate="5 Bq/kg", _id="Ac2"),
        ])
        
        self.assembly = Assembly("root", _id="root", components=[
            Component("C1", mass="1 kg", specs=[specs1], _id="C1"),
            Assembly("A1", _id="A1", components=[
                (Component("C2", mass="2 kg", specs=[specs2], _id="C2"),2), 
                Assembly("A2", _id="A2", components=[
                    (Component("C3", mass="3 kg", specs=[specs1], _id="C3"), 3)
                ])
            ])
        ])
        self.model = BgModel("test", self.assembly)
        
        self.simdb = TestingSimulationsDB()
        self.simdata = self.simdb.updatesimdata(self.model)
        
                                 
    def test_numrequests(self):
        """Test that the expected number of requests were generated"""
        self.assertEqual(len(self.simdata), 14)
        self.assertEqual(self.simdata[0].dataset[1], 'gamma')
        self.assertEqual(self.simdata[1].dataset[1], 'neutron')
        
        
    def test_emissionrate(self):
        """Test that the emissionrate is as we expect"""
        #C1, Th232: 1 kg @ 2 mBq/kg = 2 mBq
        self.assertEqual(self.simdata[2].emissionrate, (2*units.mBq).to('1/s'))
        #C2, K40: 2kg @ 100 mBq/kg, weight2 = 400 mBq
        self.assertEqual(self.simdata[6].emissionrate, 
                         (400*units.mBq).to('1/s'))
        #C3, Co60: 3kg @ 4mBq/kg, weight3 = 36 mBq/kg
        self.assertEqual(self.simdata[13].emissionrate, 
                         (36*units.mBq).to('1/s'))

        #C1, U238 neutrons: 1kg @ 1 mBq/kg*1e-6 = 1e-6 mBq/kg
        self.assertEqual(self.simdata[1].emissionrate, (1e-6*units.mBq).to('1/s'))

    def test_livetime(self):
        """Test that the calculated livetime is as we expect"""
        self.assertEqual(self.simdata[0].livetime, 1.e10*units.s)
        self.assertEqual(self.simdata[1].livetime, 1.e16*units.s)

    def test_rates(self):
        """Test that the total calculated rates are as expected"""
        rates = self.simdb.evaluate(("gammarate", "neutronrate", "rate"),
                                    self.simdata)
        #convert to dimensionless numbers to use AlmostEqual and avoid 
        #floating point nonsense. 
        self.assertAlmostEqual(rates['gammarate'].to('1/s').m, 
                               (6.1e-3*units.mBq).to('1/s').m)
        self.assertAlmostEqual(rates['neutronrate'].to('1/s').m, 
                               (3.8E-14*units.mBq).to('1/s').m)

                                     
        
        


if __name__ == "__main__":
    unittest.main()
    
        
    
