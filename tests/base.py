""" Base class for tests which require a test app and
client.
"""
from . import context  # noqa

from bgexplorer.modeleditor.modeleditor import ModelEditor
from bgexplorer.modeldb import ModelDB

from flask_bootstrap import Bootstrap
from flask import Flask
import unittest
import tempfile
import logging
import urllib
from copy import deepcopy
import bson

class TestingModelDB(ModelDB):
    """ Simplified ModelDB used for testing. Models are kept in-memory """
    
    class FakeDB(dict):
        @staticmethod
        def convert_query(query):
            if isinstance(query,dict) and '_id' in query:
                query = query['_id']
            return str(query)

        def find_one(self, query, projection=None):
            result = deepcopy(self.get(self.convert_query(query)))
            if result:
                if isinstance(projection, dict):
                    for key,val in projection.items():
                        if val is False or val is 0:
                            result.pop(key,None)
                            
            return result
        
        def replace_one(self, query, model):
            self[self.convert_query(query)] = model
            
        def insert_one(self, model):
            model['_id'] = str(bson.ObjectId())
            self[model['_id']] = model
            
        def aggregate(self, pipeline):
            #just return list of all models...
            return [deepcopy(m) for m in self.values()]
    
        def drop(self):
            self.clear()

    def connect(self, dburi=None):
        """ Use a db as a fake MongoDB collection. Queries and projections
        are not treated properly, but should work where the query is an ID
        """
        self._collection = self.FakeDB()
        
        
    def get_model_history(self, modelid):
        raise NotImplementedError("get_model_history")

    def get_current_version(self, modelname, includetemp=False):
        return 0
        

class BGExplorerTestCase(unittest.TestCase):
    """ Base Test case for web api.

        To use this as a base class for test cases, simply derive
        this class.

        The utility of this class comes in the following ways:

        1. To issue requests to the app, the client attribute can be used.

        .. code-block:: python
            self.client.post("<endpoint>", data={})

        2. The app itself can be modified from test code

        .. code-block:: python
        
        self.app.restart() # clears cache

    """

    log = logging.getLogger("test_case")

    def setUp(self):
        """ At the beginning of each class of tests, a test server
        should be set up and a test DB collection created. This is 
        a slight modification on this app's `create_app` function.
        """
        self.app = Flask("test_flask")    
        Bootstrap(self.app)
        self.modeldb = TestingModelDB(app=self.app, collection='unittest')
        self.modeleditor = ModelEditor(app=self.app, modeldb=self.modeldb)
        self.app.config['DEBUG'] = True
        self.app.config['SERVER_NAME'] = 'localhost:9999'
        self.app.test = True
        self.client = self.app.test_client()
        logging.basicConfig(level=logging.DEBUG)

    def tearDown(self):
        """ At the end of the tests, the test database should be torn down.
        This ensures that unit tests do not interfere with each other and
        that if tests are accidentally run on a production server, the
        real data and DB are not affected.
        """
        self.modeldb._collection.drop()

    def list_rules(self):
        """ Utility function for developers to see which endpoints are defined.
        Should return a list of strings in the format of:

        <endpoint> <methods, POST, GET, etc...> <url>
        """
        with self.app.app_context():
            output = []
            for rule in self.app.url_map.iter_rules():

                methods = ','.join(rule.methods)
                line = urllib.parse.unquote("{:30s} {:20s} {}".format(rule.endpoint, methods, rule.rule))
                output.append(line)
            
            return [line for line in sorted(output)]

    def check_valid_endpoint(self, response):
        """ Convenience function for checking to see if a response accesses
        a known endpoint/rule. For convenience, prints out the available endpoints
        as an easy reference for developers.
        """
        if response.status_code == 404:
            self.log.warning("Invalid Endpoint. Endpoint mapping:")
            for line in self.list_rules():
                self.log.info(line)
        assert(response.status_code != 404)
