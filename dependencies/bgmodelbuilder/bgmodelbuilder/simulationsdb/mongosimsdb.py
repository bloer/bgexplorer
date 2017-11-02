#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super

import pymongo
import bson
from time import time
from copy import copy
from collections import namedtuple
#numpy is not a strict requirement
try:
    import numpy
except:
    numpy = None

from .. import units
from .simulationsdb import SimulationsDB, SimDataMatch


MatchOverride = namedtuple("MatchOverride",["test", "buildmatch"])
MatchOverride.__doc__ = """\
Conditionally override the default query and weight for some request 
objects. 

Note: In order to order produce multiple matches from one default, one must 
provide multiple MatchOverrides with the same `test` but different `buildmatch`
functions. 

Args:
    test: a function taking a SimDataRequest and returning True to override the 
          default, False otherwise
    buildmatch: a function taking a SimDataMatch object with the default
                query and weights and modifying as necessary, returning the 
                modified match. 
"""



class MongoSimsDB(SimulationsDB):
    """
    Define a (mostly) concrete implementation of a SimulationssDB with a 
    MongoDB backend. Users may want to use this class as a base or template for 
    adding their own features. 
    
    In this implementation, each dataset document is expected to have the 
    following format:
    
    {
        "volume": "<name of simulation volume>",
        "distribution": "<distribution of primary particles in/on volume>",
        "primary": "<Name of the primary particle>",
        "spectrum": "<Emission spectrum of the primary particle>",
        "nprimaries": <# of primaries in dataset>,
        
        "counts": {
            "<count name 1>": <object1>,
            "<count name 2>": <object2>, 
        }
        "units": {
            "<count name 1>": "<unit>",
            "<count name 2>": "<unit>"
        }
    }

    Some notes:
    * "primary" may be a fundamental particle e.g. "gamma" or "neutron", or it 
      may be an isotope like "U238" or an arbitrary string like "MyFunc(a,n)". 
      In the last case, this must be specified in a querymod somewhere or given 
      in the override function NOT YET IMPLEMENTED
    
    * "spectrum" will normally be the name of a spectrum file corresponding to 
      an isotope. Can be None if the primary matches the name of the spec being 
      queried

    * additional keys are allowed and will be ignored

    * objects in the counts array may take different forms. First, the name 
      is checked against the dictionary of decoding functions in 
      `self.decoders`. 
      If it is found, that function is used to convert the value.  If no 
      decoder is registered for that name, conversion is applied by type:
        * numbers are unchanged
        * strings are evaluated through pint.UnitRegistry. If they are 
          string representations of numbers, they will be converted to 
          int or float as appropriate. Expressions and units will also 
          be interpreted.
        * lists. If list values are numbers, they will be converted to ndarrays
                 if numpy is available. If strings, they will be treated
                 as individual keywords. Mixed type lists are not allowed
        * bytes: a 1D numpy ndarray with float dtype. Will throw an error
                 if numpy is not available
      
      If a unit is listed in the "units" document, it will be applied to the 
      converted object (using `pint` units).  When combining multiple datasets,
      numeric types will be normalized by livetime and summed together, 
      UNLESS the name ends with the exact string "bins". In that case, no 
      norming or summing will happen, and an error will be generated if 
      all objects of that name are not identical. 
    
    * see `buildquery` for info on how requests are mapped to results. In 
      particular, querymods simply overwrite keys in the default query. 

    """ 
    def __init__(self, collection, basequery=None, overrides=None, **kwargs):
        """Create a new SimulationsDB interface to a mongodb backend. 

        TODO: document and add interface for `decoders`

        Args:
            collection : pymongo.Collection holding the simulation data. 
            basequery (dict): a query object that will be prepended to all 
                              queries. For example {"version":{"$gt":2.5}}
            overrides (list): List of MatchOverride tuples to modify default
                              queries/weights. This is useful e.g. for 
                              sources that expect both gamma and neutron
                              primaries. 
        """
        #initialize the DB connection
        self.collection = collection
        self.basequery = basequery or {}
        self.overrides = overrides or []
        self.decoders = {}
        
        self.index_simentries()
        
        #initialize the base class
        super().__init__(**kwargs)
        
    

    ########### required simulationsdb overrides ##############
    def findsimentries(self, request):
        """Construct a list of matches for the given request, and 
        attach data queried from the database. 
        This queries the map of additional generators registered, otherwise
        return a single default
        """
        matches = []
        query = self.buildquery(request)
        match = SimDataMatch(request, query=query, weight=1)
        for test, buildmatch in self.overrides:
            if test(request):
                matches.append(buildmatch(match.clone(deep=False)))
        if not matches:
            matches = [match]

        #attach and interpret data
        for match in matches:
            hits = tuple(self.collection.find(match.query, {'nprimaries':True}))
            match.dataset = tuple(str(d['_id']) for d in hits)
            if match.request and match.request.emissionrate:
                primaries = sum(float(d['nprimaries']) for d in hits)
                weight = match.weight or 1
                match.livetime = primaries / (match.request.emissionrate
                                              *match.weight)

        return matches
            

    def evaluate(self, values, matches):
        """Sum up each key in values, weighted by livetime.  
        If entries were all numbers, we could make this more efficient by 
        using the aggregation pipeline. But that won't work when trying to add
        histograms, so we just read each value and do the sum ourselves. 
        
        TODO: Is there an intelligent way to structure histograms to do the sum
        server-side?
        
        TODO: this function needs splitting
        """
        result = {v:0 for v in values}
        projection = {"units":True}
        for v in values:
            projection["counts."+v] = True

        for match in matches:
            dataset = match.dataset
            if not dataset:
                continue
            if not isinstance(dataset, (list, tuple)):
                dataset = (dataset,)
            
            if not match.livetime:
                raise ValueError("Cannot evaluate match with 0 livetime")

            for entry in dataset:
                #ID should be an object ID, but don't raise a fuss if not
                try:
                    entry = bson.ObjectId(entry)
                except bson.errors.InvalidId:
                    pass
                    
                doc = self.collection.find_one({'_id':entry}, projection)
                if not doc:
                    #Entry should have been for an existing document, so 
                    #something went really wrong here...
                    raise KeyError("No document with ID %s in database"%entry)
                counts = self.decodecounts(doc)
                for key, val in counts.items():
                    #TODO how to handle weird values here: 
                    if val is None:
                        continue
                    if key.endswith("bins"):
                        #make sure they're equal
                        if numpy and isinstance(result[key], numpy.ndarray):
                            if not numpy.array_equal(result[key], val):
                                raise ValueError("Unequal bins found for key "+
                                                 key)
                        elif result[key] and result[key] != val:
                            raise ValueError("Unequal bins found for key "+
                                             key)
                        else:
                            result[key] = val
                                                
                    else:
                        result[key] += val/match.livetime
                    #TODO: Need a smarter way to handle non-normalized stuff
                    

        return result
                

    ########### internal function #################
    def buildquery(self, request):
        """Evaluate the query incorporating modifiers """
        query = copy(self.basequery)
        query['volume'] = request.component.name
        query['distribution'] = request.spec.distribution
        query['primary'] = request.spec.name
        for mod in request.getquerymods():
            if mod:
                query.update(mod)
        return query

    def decodecounts(self, doc):
        """Convert a raw database result document into manipulable numbers"""

        result = dict()
        docunits = doc.get("units", {})

        for key, val in doc['counts'].items():
            if key in self.decoders:
                val = self.decoders[key](val)
            else:
                val = self.decodebytype(val)
            if key in docunits:
                val *= units[docunits[key]]
            result[key] = val

        return result
                

    def decodebytype(self, val):
        """Decode a value based on its type. Currently this will convert lists
        and bytes objects to numpy arrays, and attempt to convert strings
        to numbers. 
        TODO: Is this stupid and slow? 
        """
        #check for numpy compatibility
        if isinstance(val, (list, tuple)):
            return numpy.array(val)
        elif isinstance(val, bytes):
            return numpy.frombuffer(val)
        elif isinstance(val, str):
            try:
                return units(val)
            except units.errors.UndefinedUnitError: #this isn't compatible
                pass
        return val

    def index_simentries(self):
        """ Create indices on the simulationssdb for faster queries
        """
        self.collection.create_index([('volume', pymongo.ASCENDING),
                                      ('distribution',pymongo.ASCENDING)])
        self.collection.create_index([('primary', pymongo.ASCENDING),
                                      ('spectrum',pymongo.ASCENDING)])

   
