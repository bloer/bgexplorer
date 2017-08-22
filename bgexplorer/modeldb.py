#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

import pymongo
import re

from ..bgmodelbuilder.bgmodel import BgModel

class ModelDB(object):
    """Helper class to load/save BgModel objects to a (pymongo) database
    Args:
       dburi (str): a pymongo database URI connection string
       collection (str): the model collection as a string
    """
    def __init__(self, dburi=None, collection='bgmodels'):
        self._collectionName = collection
        self._client = None
        self._database = None
        self._collection = None
        
        if dburi:
            self.connect(dburi)

    def connect(self, dburi):
        """Connect to the server and database identified by dburi"""
        print("Connecting to mongodb server at ", dburi)

        self._client = pymongo.MongoClient(dburi)
        try:
            self._database = self._client.get_default_database()
        except pymongo.errors.ConfigurationError:
            print("WARNING: Database not provided in URI, connecting to 'test'")
            self._database = self._client.get_database('test')
        self._collection = self._database.get_collection(self.collectionName)
        #make sure the collection is properly indexed
        self._collection.create_index((('name', pymongo.ASCENDING),
                                       ('version', pymongo.DESCENDING)),
                                      unique=True);
        
    def testconnection(self):
        """Make sure we're connected to the database, otherwise raise exception
        """
        if not self._collection:
            raise exceptions.RuntimeError("No active database connection")
        
    def get_raw_model(self, query, projection=None):
        """Get the raw dict object for a model stored in the db
        Args:
            query(str or dict): pymongo query object. Should generally be a str
                or ObjectId corresponding to the model's ID or a dict with 
                'name' and 'version' keys
            projection (dict): pymongo projection doc
        """
        self.testconnection()
        return self._collection.find_one(query, projection)
        
    def get_model_history(self, modelid):
        """Helper function to get the editDetails chain for a model
           returns the models projected to edit history in a list
           with the most recent first
        """
        result = []
        projection = {'editDetails':True, 'derivedFrom':True}
        while modelid:
            model = self.get_raw_model(modelid, projection)
            if model:
                result.append(model)
                modelid = model.get('derivedFrom', None)
        return result

    def get_current_version(self, modelname):
        """Get the most recent version number for a given model name"""
        result = self.get_raw_model({'name':modelname},{'version':True})
        return result['version'] if result else 0
        
    def get_model(self, query, projection=None):
        """Load the model from query built into a BgModel object
        See `get_raw_model` for a description of the parameters
        """
        raw = self.get_raw_model(query, projection)
        return BgModel.buildfromdict(raw) if raw else None

    def write_model(self, model):
        """Write a modified model to the database. No checks are done 
        to make sure version and name are unique!
        Returns _id of model written. 

        Args:
            model (dict or BgModel): The data to be stored
        """
        self.testconnection()
        if isinstance(model, BgModel):
            model = model.todict()
        if '_id' in model:
            res = self._collection.replace_one({'_id':model['_id']}, model)
        else:
            res = self._collection.insert_one(model)

        return model.get('_id')

    def new_model(self, derivedFrom=None, temp=True):
        """Create a new model in the database, either from scratch or by 
        cloning an existing model. By default bump the version number to the
        next available for that name
        Args:
            derivedFrom (str, ObjectID): _id for parent to clone from 
            temp (bool): if true (default), append '.EDITING' to the name
        """
        model = None
        if derivedFrom:
            model = self.get_raw_model(derivedFrom)
            if not model:
                raise exceptions.KeyError("Model with id %s not found",%s)
        else:
            model = BgModel().todict()
            
        #make sure it's sane
        model['version'] = 1 + self.get_current_version(model['name'])
        model['name'] = str(model['name'])+".EDITING"
        if '_id' in model:
            del model['_id']
            
        self.write_model(model)
        #should be able to just return model, but just to be safe
        return self.get_model(model['_id'])
        
    def get_models_list(self, includetemp=False, mostrecentonly=True,
                        projection={'name':True, 'version':True,
                                    'description':True, 'editDetails':True}):

        """Get a list of all defined models, just the raw dictionary objects.
        Args:
            includetemp (bool): if true, include temporary models (i.e., with 
                names ending in '.EDITING')
            mostrecentonly (bool): if true (default), only grab the most recent
                version of each model name
            projection (dict): mongodb projection operator to apply to the 
                selection.  Use None to get the full object
        """
        self.testconnection()
        
        #use the aggregation pipeline
        pipeline = []
        if not includetemp:
            match = {'$match':{'name': {'$not':re.compile(r'\.EDITING$')}}}
            pipeline.addend(match)
        if mostrecentonly:
            pipeline.extend([
                {'$sort': {'version': pymongo.DESCENDING}},
                {'$group': {'_id':'$name', 'mostrecent': {'$first': '$$ROOT'}}},
                {'$replaceRoot': {'newRoot': '$mostrecent'}}
            ])
        if projection is not None:
            pipeline.append[{'$project': projection}]

        return self._collection.aggregate(pipeline)
            
            
