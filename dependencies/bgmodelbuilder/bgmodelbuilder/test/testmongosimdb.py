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

from ..simulationsdb.mongosimsdb import MongoSimsDB
from ..simulationsdb.simdoceval import DirectValue,DirectSpectrum
from ..simulationsdb.histogram import Histogram
from ..component import Component
from ..emissionspec import RadioactiveContam
from ..bgmodel import BgModel
from .. import units

#TODO: Don't hardcode the DB connection parameters


#callbacks for new mongosimsdb implementation
def buildquery(request):
    if not request or not request.component or not request.spec:
        return None
    request.query = {
        'volume': request.component.name,
        'distribution': request.spec.distribution,
        'primary': request.spec.name,
    }
    return [request]

def livetime(match, hits):
    return sum(doc['nprimaries'] for doc in hits)/match.emissionrate

livetimepro = {'nprimaries':True}

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
        
        
        self.simdb = MongoSimsDB(self.collection,
                                 buildqueries=buildquery,
                                 livetime=livetime,
                                 livetimepro=livetimepro)
        self.component = Component(name="V1", mass=5*units.kg,
                                   surface=2*units.cm**2,
                                   specs=[
            RadioactiveContam("P1", distribution="bulk", rate="2 Bq/kg"),
            RadioactiveContam("P3", distribution="surface", rate="5 Bq/cm**2")
                                   ])
        self.model = BgModel(name="testmongo")
        self.model.assemblyroot.addcomponent(self.component)
        self.matches = self.simdb.updatesimdata(self.model)
        
        
    def tearDown(self):
        self.db.drop_collection(self.collection.name)

    
    def test_find_default(self):
        self.assertEqual(len(self.matches), 2)
        for match in self.matches:
            self.assertAlmostEqual(match.livetime.to('s').m, 1e5)
            self.assertEqual(len(match.dataset), 1)
                

    def test_eval(self):
        vals = (DirectValue("counts.C1"),
                DirectValue("counts.C2",unitkey="units.C2"))
        result = self.simdb.evaluate(vals, self.matches)
        
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0].to("1/s").m, 110./1e5)
        self.assertAlmostEqual(result[1].to("1/(s*kg*keV)").m, 220./1e5)
        

    @unittest.skipUnless(numpy, "requires numpy")
    def test_numpy_eval(self):
        vals = (DirectSpectrum("counts.C3"),)
        result = self.simdb.evaluate(vals, self.matches)
        hist = result[0]
        self.assertIsInstance(hist, Histogram)
        self.assertIsInstance(hist.hist, units.Quantity)
        self.assertIsInstance(hist.hist.m, numpy.ndarray)
        self.assertAlmostEqual(hist.hist[1].to('1/s').m, 11./1e5)


        
