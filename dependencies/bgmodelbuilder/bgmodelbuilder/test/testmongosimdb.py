import unittest
try:
    import pymongo
    from pymongo.errors import ConnectionFailure
except:
    pymongo = None

try:
    import numpy
except:
    numpy = None

from ..simulationsdb.mongosimsdb import MongoSimsDB, MatchOverride
from ..component import Component
from ..emissionspec import RadioactiveContam
from .. import units

#TODO: Don't hardcode the DB connection parameters

@unittest.skipUnless(pymongo,"requires pymongo")
class TestMongoSimsDB(unittest.TestCase):
    """Test that a MongoSimsDB interface returns expected results"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = pymongo.MongoClient("localhost:27017", #default
                                          connect=True,
                                          connectTimeoutMS=500,
                                          socketTimeoutMS=500,
                                          serverSelectionTimeoutMS=500,)
        #suggested way to test if connection is live:
        try:
            self.client.is_primary
            self.db = self.client['test']
        except:
            self.client = None
            


    def setUp(self):
        """Stand up the collection and fill with sample data"""
        if not self.client:
            self.skipTest("No mongodb connection")
            return
        
        self.collection = self.db['testmongosimdb']
        self.db.drop_collection(self.collection.name) #mnake sure its empty
        
        #fill a few entries
        self.collection.insert_one({
            '_id': "dataset1",
            "volume": "V1",
            "distribution": "bulk",
            "primary": "P1",
            "nprimaries": 1e6, 
            "counts": {
                "C1": 10,
                "C2": 20,
                "C3": [0., 1., 2., 1., 0.],
            },
            "units": {
                "C2": "1/(kg*keV)"
            }
        })
        self.collection.insert_one({
            '_id': "dataset2",
            "volume": "V2",
            "distribution": "bulk",
            "primary": "P2",
            "spectrum": "S2",
            "nprimaries": 1e6,
            "counts": {
                "C1": 11,
                "C2": 21,
                "C3": [0., 1., 2., 1., 0.],
            },
            "units": {
                "C2": "1/(kg*keV)"
            }
        })
        self.collection.insert_one({
            '_id': "dataset3",
            "volume": "V1",
            "distribution": "surface",
            "primary": "P3",
            "nprimaries": 1e6,
            "counts": {
                "C1": 100,
                "C2": 200,
                "C3": [0., 10., 20., 10., 0.],
            },
            "units": {
                "C2": "1/(kg*keV)"
            }
        })
        
        
        self.simdb = MongoSimsDB(self.collection)
        self.component = Component(name="V1", mass=5*units.kg,
                                   surface=2*units.cm**2,
                                   specs=[
            RadioactiveContam("P1", distribution="bulk", rate="2 Bq/kg"),
            RadioactiveContam("P3", distribution="surface", rate="5 Bq/cm**2")
                                   ])
        
        
    def tearDown(self):
        self.db.drop_collection(self.collection.name)

    
    def test_find_default(self):
        for request in self.component.getsimdata([], rebuild=True):
            matches = self.simdb.findsimentries(request)
            self.assertEqual(len(matches), 1)
            self.assertAlmostEqual(matches[0].livetime.to('s').m, 1e5)
            self.assertEqual(len(matches[0].dataset), 1)
                                   
    def test_querymod(self):
        self.component.querymod = {"volume": "V2", "primary": "P2"}
        requests = self.simdb.attachsimdata(self.component)
        self.assertEqual(len(requests[0].matches),1)
        self.assertEqual(len(requests[0].matches[0].dataset),1)
        self.assertEqual(requests[0].matches[0].dataset[0],'dataset2')
        
    def test_override(self):
        def addspec(match):
            match.weight = 10
            match.query['primary'] = "P2"
            match.query['spectrum'] = "S2"
            match.query.pop('volume',None)
            return match

        override=MatchOverride(lambda m: m.spec.name=="P1", addspec)
        self.simdb.overrides.append(override)
        requests = self.simdb.attachsimdata(self.component)
        self.assertEqual(len(requests[0].matches),1)
        self.assertEqual(requests[0].matches[0].dataset[0],'dataset2')
        self.assertAlmostEqual(requests[0].matches[0].livetime.to('s').m, 1e4)
        self.assertEqual(len(requests[1].matches),1)
        

    def test_eval(self):
        requests = self.simdb.attachsimdata(self.component)
        matches =  sum((r.matches for r in requests), [])
        result = self.simdb.evaluate(("C1", "C2"), matches)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result["C1"].to("1/s").m, 110./1e5)
        self.assertAlmostEqual(result["C2"].to("1/(s*kg*keV)").m, 220./1e5)
        self.assertAlmostEqual(result["C1"].to("1/s").m, 110./1e5)
        

    @unittest.skipUnless(numpy, "requires numpy")
    def test_numpy_eval(self):
        requests = self.simdb.attachsimdata(self.component)
        matches =  sum((r.matches for r in requests), [])
        result = self.simdb.evaluate(("C3",), matches)
        self.assertAlmostEqual(result["C3"][1].to('1/s').m, 11./1e5)


        
