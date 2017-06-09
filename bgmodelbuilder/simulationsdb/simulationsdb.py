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


class SimulationsDB(object):
    """Store pre-calculated conversion efficiencies, and calculate 
    reduced event values
    """
    
    def __init__(self, model=None, lastmod=None):
        """Initialize a new DB instance.  The model and lastmod 

        Args:
            model (id): unique identifier of the model to consider for cache
            lastmod (timestamp): time the model was last modified, to calculate
                cache stale state. With None (default), the cache should always
                be refreshed. A value of 0 should never expire the cache
        """
        
        self.setmodel(model, lastmod)

        
    def setmodel(self, model=None, lastmod=None):
        """Set the model for cache state. See the constructor for details"""
        self._model = model
        self._lastmod = lastmod
        self.expirecache(self, model, lastmod)


    def findsimentries(self, component, spec):
        """Find all conversioneffs that should be associated to comp, spec"""
        #first, try the cache
        result = self.findcachedsimentries(component, spec)
        if result is None:
            #there is no valid cache, so run the query
            query = self.calculatequery(component, spec, 
                                        component.getquerymod())
            result = runquery(query)
            if result is not None:
                #we have a new result, update the cache
                self.cachesimentries(component, spec, result)

        return result or [] #make sure we can iterate over result

    def evaluate(self, values, compspecs):
        """Evaluate the reduced sum for values over the list of compspecs
        Args:
            values (list): list of identifiers for values. E.g., names
                           of columns in the db entries
            compspecs (list): list of (component,spec) pairs to caluclate 
                              these values for

        Returns:
            result (dict): dictionary of results for each key in values
        """
        #first, try the cache
        result = self.getcachedreductions(values, compspecs)
        if result is None or len(result) != len(values):
            #there is no valid cache, so recalculate
            #first we need the list of effs for each comp, spec
            simweights = {}
            for comp, spec in compspecs:
                rate = spec.emissionrate(comp)
                if rate>0:
                    for sim in self.findsimentries(comp, spec):
                        simweights[sim] = rate + simweights.get(sim,0)

            #now we have a rolled-up list of conversions, so calculate the vals
            result = self.reduce(values, simweights.items())
            if result is not None:
                #we have a new result, update the cache
                self.cachereductions(values, compspecs, simweights, result)
        return result
            
        
    def calculatecacheid(self, compspecs):
        """For the list of (component, spec) pairs in compspecs, calculate a 
        unique cache value. By default, convert all individual IDs to 
        strings, concatenate, and calculate an md5sum base64 encoded
        """
        #I think this only works in python3...
        myhash =md5(''.join(str(c.getspecid(s)).encode() for c,s in compspecs)) 
        return b64encode(myhash.digest())
        
    #the following should be overridden by derived classes
    def expirecache(self, model=None, lastmod=None):
        """Remove any invalid cache entries"""
        pass
    
    def defaultquery(self, component, spec):
        """Generate the default query for the associated component, spec"""
        pass

    def calculatequery(self, component, spec, compmod, specmod):
        """Calculate the full query accounting for querymods"""
        pass

    def runquery(self, query, idonly=True):
        """Run the query against the DB. Return a list of datasets or ids
        """
        pass
        
    def reduce(self, values, entryweights):
        """For each entry in values, calculate the result summed over entries
        
        Args:
            values (list): List of the values to calculate. Could be strings or
                more complicated objects understood by the concrete 
                implementation. 
            entryweights (dict): dict of {id: weight} pairs, where ID uniquely 
                identifies a ConversionEff stored in the DB, or may be an 
                actual ConversionEff object depending on implementation. 

        Returns:
             reduced (dict): dict of {value:reduced result}
        """
        pass

    def findcachedsimentries(self, component, spec):
        """Find cached list of conversion effs for this component, spec pair"""
        return None

    def cachesimentries(self, component, spec, result):
         """Store newly matched conversions in the cache"""
         pass

    def getcachedreductions(self, values, compspecs):
        """Retrieve precalculated reduced vales in the cache"""
        return None

    def cachereductions(self, values, compspecs, simweights, result):
        """Store calculated reductions in the cache

        Args: 
            cacheid (var): index key for the cache entry
            result (dict): dict of {valuetype: calculated result} pairs
        """
        pass
