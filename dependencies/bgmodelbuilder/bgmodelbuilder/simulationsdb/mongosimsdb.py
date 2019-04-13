#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super

import pymongo
import bson
from time import time
from copy import copy
from collections import namedtuple
import json
import logging

from .. import units
from .simulationsdb import SimulationsDB, SimDataMatch

log = logging.getLogger(__name__)

class MongoSimsDB(SimulationsDB):
    """
    Define a (mostly) concrete implementation of a SimulationssDB with a 
    MongoDB backend. Users may want to use this class as a base or template for 
    adding their own features. 
    
    In this implementation, no assumptions are made about the structure of each 
    dataset.  The class constructor takes several functions that are called
    to generate queries.  Values requested for ecvaluation should be SimDocEval
    objects which know how to parse and combine values. 

    """ 
    def __init__(self, collection, buildqueries, livetime, livetimepro=None, 
                 summaryview=None,
                 **kwargs):
        """Create a new SimulationsDB interface to a mongodb backend. 

        Args:
            collection : pymongo.Collection holding the simulation data. Any 
                         necessary indices should already by applied
            buildqueries (func): a function to generate database queries for 
                              a SimDataRequest object. For each separate
                              query generated, the function should call
                              `request.addquery` with appropriate weight. 
                              This function should also take into account 
                              modifiers to the queries accessible from 
                              `request.getquerymods`. A static function 
                              `MongoSimsDB::modquery` to do a simple
                              `dict.update` for each mod. 
            livetime (func):  a function to calculate the livetime for a 
                              collection of datasets. Takes 2 arguments:
                              a SimDataMatch and a list of documents retrieved
                              from the database. Do not modify the match object!
            livetimepro (dict): projection document when querying for livetime
            summaryview (dict): mapping document to apply to each entry
                                when producing a summary table

            
        """
        #initialize the DB connection
        self.collection = collection
        self.buildqueries = buildqueries
        self.livetime = livetime
        self.livetimepro = livetimepro
        
        #initialize the base class
        super().__init__(**kwargs)
        
    

    ########### required simulationsdb overrides ##############
    def genqueries(self, match, findnewdata=True):
        # call the callback to generate queries
        matches = self.buildqueries(match)
        # attach and interpret data
        if findnewdata:
            #make sure its iterable
            if not matches:
                matches = []
            elif not isinstance(matches, (list, tuple, set)):
                matches = [matches]
        
            for match in matches:
                hits = tuple(self.collection.find(match.query, 
                                                  self.livetimepro))
                dataset = list(str(d['_id']) for d in hits)
                livetime = self.livetime(match, hits)

                if not dataset:
                    match.addstatus('nodata')

                match.dataset = dataset
                match.livetime = livetime
        return matches
    
    
    def evaluate(self, values, matches):
        """Sum up each key in values, weighted by livetime.  
        If entries were all numbers, we could make this more efficient by 
        using the aggregation pipeline. But that won't work when trying to add
        histograms, so we just read each value and do the sum ourselves. 

        Args:
        values (list) : list of SimDocEval objects that specify the projection
                        and interpretation of each dataset
        matches (list): list of SimDataMatch objects to calculate and reduce
                        each value over
        
        """
        result = [0]*len(values)
        projection = {}
        for v in values:
            v.project(projection)
        
        matches = matches if isinstance(matches,(list, tuple)) else [matches]
        for match in matches:
            dataset = match.dataset
            if not dataset:
                continue
            if not isinstance(dataset, (list, tuple)):
                dataset = (dataset,)
            
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
                
                for i,v in enumerate(values):
                    val = v.norm(v.parse(doc, match), match)
                    result[i] = v.reduce(val, result[i])

        return result

    def getdatasetdetails(self,dataset):
        # dataset should be an ID but may be stringified
        try:
            dataset = bson.ObjectId(dataset)
        except bson.errors.InvalidId: #not an object ID
            pass
        return self.collection.find_one(dataset)
        
        #if isinstance(dataset, str) and dataset.startswith('['):
        #    try:
        #        dataset = json.loads(dataset)
        #    except json.JSONDecodeError:
        #        log.error("Can't convert from string list %s",dataset)
        #if not isinstance(dataset,(list, tuple)):
        #    dataset = [bson.ObjectId(dataset)]
        #return list(self.collection.find({'_id':{'$in':dataset}}))
        #return [self.collection.find_one({'_id':entry}) for entry in dataset]
                
    @staticmethod
    def modquery(query, request):
        """Utility function implementing a very basic query update process.
        For each requested modifer in the request, the query is updated directly
        (using `dict.update`). This is mostly to serve as an example of how
        to implement a more useful interperter. 
        """
        for mod in request.getquerymods():
            if mod:
                query.update(mod)
        return query
    
    def runquery(self, query, projection=None, sort=None):
        pipeline = []
        if query:
            pipeline.append({'$match': query})
        if sort:
            pipeline.append({'$sort': sort})
        if projection:
            pipeline.append({'$project': projection})
        return self.collection.aggregate(pipeline)
