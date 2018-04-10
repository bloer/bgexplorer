""" simdatamatch.py

Defines the SimDataMatch class which is used to map simulation data onto
components under an assembly tree
"""

#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super
from functools import wraps, reduce
import operator
import copy 

from ..mappable import Mappable
from ..common import to_primitive, ensure_quantity

 
class SimDataMatch(Mappable):
    """Translate a request for simulation data for a spec placed in the 
    Assembly tree into a full SimulationsDB query and attach matching
    datasets if found
    
    Args:
        request:  The parent SimDataRequest to generate the query
        query:    The full query built from the requests' inputs
        datasets: List of simulation datasets matching the full query
        weight (float): additional weighting applied to this query
                        E.g., neutrons per decay of U238
        livetime: Effective livetime of these datasets compared to the 
                  emissionrate of the request
        status (str): space-separated list of status tags. Will be used as 
                      html classes for web interface
    """
    def __init__(self, request=None, query=None, dataset=None, 
                 weight=1, livetime=None, status=None, **kwargs):
        super().__init__(**kwargs)
        self.request = request
        self.query = query
        self.dataset = dataset
        self.weight = weight
        self.livetime = ensure_quantity(livetime, "year")
        self.status = status or ""

    def todict(self):
        mydict = copy.copy(self.__dict__)
        mydict.pop('request',None) #will cause circular recursion otherwise!
        return to_primitive(mydict)

    @property
    def emissionrate(self):
        return self.request.emissionrate*self.weight if self.request else None
        
    def addstatus(self, tag):
        """Treat status as a space-separated list of tags"""
        status = set(self.status.split())
        status.add(tag)
        self.status = ' '.join(status)
    
    def popstatus(self, tag):
        """Remove tag from space-separated list of status tags"""
        status = set(self.status.split())
        if tag in status:
            status.remove(tag)
        self.status = ' '.join(status)
        

    #forward some useful attributes from the request
    @property
    def assemblyPath(self):
        return self.request.assemblyPath if self.request else None
    @property
    def spec(self):
        return self.request.spec if self.request else None
    @property
    def component(self):
        return self.request.component if self.request else None
        
    def __eq__(self, other):
        try:
            return (self.request == other.request 
                    and self.query == other.query
                    and self.dataset == other.dataset
                    and self.weight == other.weight
                    and self.livetime == other.livetime)
        except AttributeError:
            return False
        
class SimDataRequest(object):
    """ Match simulation data to a component within an assembly hierarchy
    and associated emission specs. Generating the final query, livetime
    and attaching simulation data are the responsibility of the user's
    SimulationsDB implementation.
    
    

    Args:
        assemblyPath (tuple): Path from assembly root to component which "owns"
                              the specs, ordered from branch to leaf
        spec (EmissionSpec): Reference to the relevant spec with non-zero 
                              emission rate
        weight (float):       Total weight of the leaf component summed over the
                              assembly path. Will be calculated if not provided
        emissionrate (float): Total absolute emission rate for this spec and 
                              component. If not provided, will be calculated
        matches:              List of SimDataMatch queries and matching data
    """

    def __init__(self, assemblyPath=None, spec=None, weight=None,
                 emissionrate=None, matches=[], **kwargs):
        super().__init__(**kwargs)
        self.assemblyPath = assemblyPath
        if isinstance(self.assemblyPath, list):
            self.assemblyPath = tuple(self.assemblyPath)
        self.spec = spec
        self._weight = weight
        self._emissionrate = ensure_quantity(emissionrate, "1/s")
        self.matches = [SimDataMatch(**ds) if isinstance(ds,dict) else ds
                        for ds in matches]
        for ds in self.matches:
            ds.request = self
        

    def recalculate(self):
        """ Recalculate all cached values """
        self._weight = self._calcweight()
        oldemissionrate = self._emissionrate
        self._emissionrate = self._calcemissionrate()
        if self._emissionrate and self._emissionrate.n:
            for match in self.matches:
                if match.livetime:
                    match.livetime *= oldemissionrate / self._emissionrate
        
        
    def _calcweight(self):
        if self.assemblyPath is not None:
            if (len(self.assemblyPath)>1 and 
                hasattr(self.assemblyPath[0],'getchildweight')):
                #calculate product of weights
                return reduce(operator.mul,
                              (p.getchildweight(c) for p,c in 
                               zip(self.assemblyPath[:-1],
                                   self.assemblyPath[1:])),
                              1)
                          

            else:
                return 1
        return None

    def _calcemissionrate(self):
        if (self.assemblyPath 
            and hasattr(self.spec,'emissionrate')
            and self.weight is not None):
            return self.weight * self.spec.emissionrate(self.component)
        return None

    def getquerymods(self):
        """Get a list of all querymods for this assemblyPath and spec"""
        #querymods can be attached to Components, Placements, and BoundSpecs
        if not self.assemblyPath or not self.spec:
            return []
                
        result = []
        for parent, child in zip(self.assemblyPath[:-1], self.assemblyPath[1:]):
            if parent.querymod:
                result.append(parent.querymod)
            #find the Placement for child
            for p in parent.components:
                if p.component == child and p.querymod:
                    result.append(p.querymod)

        if self.component.querymod:
            result.append(self.component.querymod)
        
        
        #find the BoundSpec this spec belongs to
        for bs in self.component._specs:
            if ((bs.spec == self.spec or 
                 self.spec in getattr(bs.spec,'subspecs',[]))
                and bs.querymod):
                result.append(bs.querymod)
                #should only appear once. I think?
                break
        
        return result
    
    @property
    def weight(self):
        if self._weight is None:
            self._weight = self._calcweight()
        return self._weight

    @property
    def emissionrate(self):
        if self._emissionrate is None:
            self._emissionrate = self._calcemissionrate()
        return self._emissionrate

    @property
    def component(self):
        return self.assemblyPath[-1] if self.assemblyPath else None
        
    def addquery(self, query, **kwargs):
        """Add a new SimDataMatch object to this request. If the object 
        already has associated matches and an equal match already exists, 
        the old match is returned instead.
        Args:
            query: query string or document appropriate for the concrete
                   SimulationsDB instance. 
            **kwargs: Other arguments are passed to the SimDataMatch
                      constructor
        Returns:
            match: The newly created SimDataMatch object
        """
        kwargs.setdefault('status','newmatch')
        weight = kwargs.get('weight',1)
        newmatch = SimDataMatch(request=self, query=copy.copy(query), **kwargs)
        oldmatch = None
        #see if we already have an existing match
        for amatch in self.matches:
            if amatch.query == query:
                oldmatch = amatch
                if weight != oldmatch.weight:
                    oldmatch.addstatus("weightchanged")
                    oldmatch.weight = weight #todo recalculate livetime too
                return oldmatch

        #if we get here, there was no prior match
        self.matches.append(newmatch)
        return newmatch
        
        
    def todict(self):
        #want to not transform the simdatamatch objects into IDs
        mydict = copy.copy(self.__dict__)
        matches = to_primitive(mydict.pop('matches'), replaceids=False)
        mydict = to_primitive(mydict)
        mydict['matches'] = matches
        return mydict
