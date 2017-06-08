""" mongosimsdb.py

Define a (mostly) concrete implementation of a SimulationssDB with a MongoDB 
backend. User classes should inherit from this class and override the 
following methods: 

index_simentries: create mongodb indexes on the simulations collection

default_query: how to match conversion entries to components?
               Might be model dependent

reduce: calculate a reduced value. The version in this class assumes
        all requested values are top-level keys in the document and are 
        simply summed.  

expirecache: Does 2 things: binds the cache collection to self._cache
             and removes any entries older than lastmod. Override this 
             if model is not castable to a string
""" 

#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super

import pymongo

from .simulationssdb import SimulationsDB

class MongoSimsDB(SimulationsDB):
    def __init__(self, database, **kwargs):
        """Create a new db instance, bound to database, which should be 
        a valid pymongo Database instance. 
        """
        #initialize the DB connection
        self._db = database
        self._cache = None #this will be updated in super() constructor

        self.index_simentries()
        
        #initialize the base class
        super().__init__(**kwargs)
        
    ########## cache functions ########
    def expirecache(self, model=None, lastmod=None):
        """Remove old cache entries. lastmod is a timestamp
        if model is None, disable cache
        if lastmod is None, clear cache
        """
        if model:
            self._cache = self._db.cache[str(model)]
            filter_ = {} if lastmod is None else {'timestamp':{'$lt'<lastmod}}
            self._cache.delete_many(filter_)
        else:
            self._cache = None

    def findcachedsimentries(self, component, spec):
        if not self._cache:
            return None
        #use the same cacheid as for values
        _id = self.calculatecacheid( ((component, spec)) )
        doc = self._cache.find_one(_id, projection={'simulations':True})
        if doc:
            return doc['simulations']
        return None
    
    def cachesimentries(self, component, spec, result):
        if self._cache:
            _id = self.calculatecacheid( ((component, spec)) )
            self._cache.update_one({'_id':_id}, 
                                   {'$set':{'simulations':result}},
                                   upsert=True)

    def getcachedreductions(self, cacheid, values):
        if not self._cache:
            return None
        doc = self._cache.find_one(cacheid, projection={'reductions': True})
        if doc:
            return {key:val for key in values if key in doc['reductions']}
        return None

    def cachereductions(self, cacheid, result):
        if self._cache:
            setkeys = {'reductions.%s'%key:val for key,val in result.items()}
            self._cache.update_one({'_id':cacheid}, {'$set': setkeys},
                                   upsert=True)
    


    ############# query functions ####################
    def calculatequery(self, component, spec, querymod):
        #first, do we override the whole thing? 
        query = self.default_query(component, spec)
        if 'override' in querymod:
            query = copy(querymod['override'])

        #now go through each key
        for key in query:
            if 'override_keys' in querymod and key in querymod['override_keys']:
                query[key] = querymod['override_keys'][key]
            if 'union_keys' in querymod and key in querymod['union_keys']:
                query[key] = {'$or': [query[key], querymod['union_keys'][key]]}
            if ('intersect_keys' in querymod 
                and key in querymod['intersect_keys']):
                query[key] = {'$and': [query[key], 
                                      querymod['intersect_keys'][key] ]}
            if 'exclude_keys' in querymod and key in querymod['exclude_keys']:
                query[key] = {'$and': [query[key], 
                                       {'$not':querymod['exclude_keys'][key]} ]}
        #now do combinations on the whole thing
        if 'union' in querymod:
            query = {'$or': [query, querymod['union']] }
        if 'intersect' in querymod:
            query = {'$and': [query, querymod['intersect']] }
        if 'exclude' in querymod:
            query = {'$and': [query, {'$not': querymod['exclude'] }] }
        
        return query
        
    def runquery(self, query, idonly=True):
        """Run the query against the DB. Return a list of ConversionEffs or ids
        The query itself should be a valid pymongo query dictionary
        What kind of errors can be thrown here? InvalidDocument for sure
        What do we do with errors????
        """
        filter_ = {'_id':True} if idonly else {}
        result = self._db.simulations.find(query, filter_)
        return [d['_id'] for d in result] if idonly else list(result)

    ############ users should override: #############
    def default_query(self, component, spec):
        """Not really adding much to the base here"""
        return {'volume': component.name,
                'source': spec.name, 
                'distribution': spec.distribution,
               }
    
    def index_simulations(self):
        """ Create any indices on the simulationssdb for faster queries
        The collection name is assumed to be 'simulations'
        """
        self._db.simulations.create_index([('volume':pymongo.ASCENDING),
                                           ('source':pymongo.DESCENDING)])

    def reduce(self, values, entryweights):
        """For each entry in values, calculate the result summed over entries
        
        Args:
            values (list): List of the values to calculate. Could be strings or
                more complicated objects understood by the concrete 
                implementation. Here assumed to be IDs
            entryweights (list): list of (id, weight) pairs, where ID uniquely 
                identifies a ConversionEff stored in the DB, or may be an 
                actual ConversionEff object depending on implementation. 

        Returns:
             reduced (dict): dict of {value:reduced result}


        This version assumes that each 'value' is a key in the objects 
        in the 'simulations' collection, and that the reduction is simple 
        addition
        """
        #there doesn't seem to be a sensible way to do lookups...
        getweight = {'$let':{
            'vars':{'keys': entryweights.keys(), 
                    'weights': entryweights.values()},
            'in':{'$arrayElemAt':["$$weights",
                                  {'$indexOfArray':["$$keys",'$_id']}] }
        }}
        reducer={key:{'$sum':{'$multiply':['$'+key,'$_weight']}} 
                 for key in values}
        reducer['_id'] = None
        pipeline = [
            #select the entries by id in entryweights
            {'$match':{'_id':{'$in':entryweights.keys()}}},
            #lookup the entry's weight
            {'$addFields': {'_weight': getweight}}, 
            #reduce
            {'$group': reducer},
            #remove the '_id' field so length matches
            {'$project': {'_id':False}}
        ]
        #these should be existing documents so there must be a single result
        return self._db.simulations.aggregate(pipeline).next()

