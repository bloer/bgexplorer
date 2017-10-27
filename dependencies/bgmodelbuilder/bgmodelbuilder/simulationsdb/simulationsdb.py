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
    
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize a new DB instance. Doesn't do anyhing yet."""
        super().__init__(*args, **kwargs)


    def attachsimdata(self, assembly):
        """ Find all simulation data for the entire assembly and attach 
        to the appropriate places. Mark the `status` attribute on SimDataMatches
        to reflect changes against previous values.
        """
        requests = assembly.getsimdata(path=(assemby,), rebuild=True, 
                                       children=True)
        for request in requests:
            newmatches = self.findsimentries(request)
            for newmatch in newmatches:
                #shouldn't be necessary, but just to make sure:
                newmatch.request = request

                #update status
                #see if there is an existing match with the same query
                oldmatch = None
                for match in request.simdata:
                    if match.query == newmatch.query:
                        oldmatch = match
                        break

                if not oldmatch:
                    newmatch.status += " new "
                else:
                    if newmatch.datasets != oldmatch.datasets:
                        if len(newmatch.datasets) > len(oldmatch.datasets):
                            newmatch.status += " newdata "
                        elif len(newmatch.datasets) < len(oldmatch.datasets):
                            newmatch.status += "dataremoved "
                        else:
                            newmatch.status += " datachanged "
                    if newmatch.weight != oldmatch.weight:
                        newmatch.status += " weightchanged "
                    if newmatch.livetime > oldmatch.livetime:
                        newmatch.status += " livetimeincreased "
                    elif newmatch.livetime < oldmatch.livetime:
                        newmatch.status += " livetimedecreased "
            request.simdata = newmatches
        return requests

        
    def findsimentries(self, request):
        """Find all SimDataMatches that should be associated to the request. 
        To allow comparison to previous versions and modification of status
        values, request should NOT be modified, but SimDataMatches returned
        as a list. 
        Args:
            request (SimDataRequest): contains placement path and spec
        Returns:
            List of SimDataMatch objects to be filled for this pair. 
            Each should have the `query` attribute set, and, if matching 
            datasets are found, the `weight` and `livetime` attributes
        """
        raise NotImplementedError


    def evaluate(self, values, matches):
        """Evaluate the reduced sum for values over the list of compspecs
        Args:
            values (list): list of identifiers for values. E.g., names
                           of columns in the db entries
            matches (list): list of SimDataMatch objects
                            to caluclate these values for

        Returns:
            result (dict): dictionary of results for each key in values
        """
        raise NotImplementedError
                    
        
    def defaultquery(self, request):
        """Generate the default query for the associated component, spec"""
        pass

    def runquery(self, query, idonly=True):
        """Run the query against the DB. Return a list of datasets or ids
        """
        pass
        
    
