""" simulationsdb.py

Defines the base class for a SimulationsDB. Methods must be overloaded by
the users' concrete derived class. 

A 'conversion efficiency' is the probability that a radioactive decay of a given
spectrum at a given location in the experiment geometry will produce an event 
of interest. Most frequently these are determined by simulations. The 
SimulationsDB tracks all known conversion effs and calculates reduced event
quantities. 
""" 

#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super
from collections import namedtuple
from base64 import b64encode
from hashlib import md5

from .. import units
from .simdatamatch import SimDataMatch

class SimulationsDB(object):
    """Abstract class to be implemented by user. 

    SimulationsDB serves 2 main purposes: 
    1. Translate requests for simulation data for a given assembly tree and 
       material spec into real database queries and find datasets matching
       those queries. 
    2. Calculate quantities (e.g. event rates) for matching datasets

    Auxiliary functions include:
    * listing the types of calculated quantities that the class knows how to 
      handle (Not yet implemented)

    TODO: Add an argument to attach a caching layer here
    
    """
    
    def __init__(self, app=None, *args, **kwargs):
        """Initialize a new DB instance. 
        Args:
            app: a Flask application object to register with
        """
        super().__init__(*args, **kwargs)
        self.app = app
        if app:
            self.init_app(app)


    def attachsimdata(self, assembly):
        """ Find all simulation data for the entire assembly and attach 
        to the appropriate places. Mark the `status` attribute on SimDataMatches
        to reflect changes against previous values.
        """
        requests = assembly.getsimdata(path=(assembly,), rebuild=True, 
                                       children=True)
        for request in requests:
            oldmatches = request.matches
            request.matches = []
            newmatches = self.findsimentries(request)
            #now look for matches that were present before
            for oldmatch in oldmatches:
                for newmatch in newmatches:
                    if oldmatch.query == newmatch.query:
                        newmatch.popstatus('newmatch')
                        #figure out some statuses
                        if oldmatch.weight != newmatch.weight:
                            newmatch.addstatus('weightchanged')
            #todo: do something with obsolete matches?                        
        return requests

        
    def findsimentries(self, request):
        """Find all SimDataMatches that should be associated to the request. 
        New SimDataMatch objects should be added to the request via
        `request.addquery`, and the resulting `request.matches` object should 
        be returned
        Args:
            request (SimDataRequest): contains placement path and spec
        Returns:
            List of SimDataMatch objects to be filled for this pair. 
            Each should have the `query` attribute set, and, if matching 
            datasets are found, the `weight` and `livetime` attributes. 
            Note: a list with SimDataMatches with empty datasets is the 
            recommended method to indicate that no data was found in the DB
            BUT an appropriate query can be generated. This can be used to 
            generate new datasets. 
        """
        raise NotImplementedError


    def evaluate(self, values, matches):
        """Evaluate the reduced sum for values over the list of emissionspecs
        Args:
            values (list): list of identifiers for values. E.g., names
                           of columns in the db entries
            matches (list): list of SimDataMatch objects
                            to caluclate these values for

        Returns:
            result (list): list of computed results in same order as values. 

        TODO: How to distinguish incorrect vs empty value requests?
        """
        raise NotImplementedError
                    
        
    def getdatasetdetails(self, datasetid):
        """Return an object with detailed info about a dataset"""
        raise NotImplementedError
    
    def defaultquery(self, request):
        """Generate the default query for the associated component, spec"""
        pass

    def runquery(self, query, idonly=True):
        """Run the query against the DB. Return a list of datasets or ids
        """
        pass
        
    
    def init_app(self, app):
        """Register ourselves as the official SimulationsDB extension"""
        app.extensions['SimulationsDB'] = self
