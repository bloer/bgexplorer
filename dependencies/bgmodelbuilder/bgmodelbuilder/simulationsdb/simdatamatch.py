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
from ..common import to_primitive
from .. import component, compspec

 
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
        self.livetime = livetime
        self.status = status or ""

    def todict(self):
        mydict = copy(self.__dict__)
        mydict.pop('request',None) #will cause circular recursion otherwise!
        return to_primitive(mydict)
        
class SimDataRequest(object):
    """ Match simulation data to a component within an assembly hierarchy
    and associated emission specs. Generating the final query, livetime
    and attaching simulation data are the responsibility of the user's
    SimulationsDB implementation.
    
    

    Args:
        assemblyPath (tuple): Path from assembly root to component which "owns"
                              the specs, ordered from branch to leaf
        spec (ComponentSpec): Reference to the relevant spec with non-zero 
                              emission rate
        weight (float):       Total weight of the leaf component summed over the
                              assembly path. Will be calculated if not provided
        emissionrate (float): Total absolute emission rate for this spec and 
                              component. If not provided, will be calculated
        simdata:              List of SimDataMatch queries and matching data
    """

    def __init__(self, assemblyPath=None, spec=None, weight=None,
                 emissionrate=None, simdata=[], **kwargs):
        super().__init__(**kwargs)
        self.assemblyPath = assemblyPath
        if isinstance(self.assemblyPath, list):
            self.assemblyPath = tuple(self.assemblyPath)
        self.spec = spec
        self._weight = weight
        self._emissionrate = emissionrate
        self.simdata = [SimDataMatch(**ds) if isinstance(ds,dict) else ds
                        for ds in simdata]
        for ds in self.simdata:
            ds.request = self
        

    def recalculate(self):
        """ Recalculate all cached values """
        self._weight = self._calcweight()
        oldemissionrate = self._emissionrate
        self._emissionrate = self._calcemissionrate()
        if self._emissionrate:
            for match in self.simdata:
                if match.livetime:
                    match.livetime *= oldemissionrate / self._emissionrate
        
        
    def _calcweight(self):
        if self.assemblyPath is not None:
            if (len(self.assemblyPath)>1 and 
                isinstance(self.assemblyPath[0],component.Assembly)):
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
            and isinstance(self.spec, compspec.ComponentSpec)
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
        
    def todict(self):
        #want to not transform the simdatamatch objects into IDs
        mydict = copy.copy(self.__dict__)
        simdata = to_primitive(mydict.pop('simdata'), replaceids=False)
        mydict = to_primitive(mydict)
        mydict['simdata'] = simdata
        return mydict
