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
from ..component import Placement

 
class AssemblyPath(list):
    """Wrapper class to store deep assembly hierarchies, converts to compact
    storage form
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def weight(self):
        """Get the total weight for this path"""
        if not self: 
            return None
        return reduce(operator.mul,(p.weight for p in self),1)
    
    def append(self, other):
        if isinstance(other, (list,tuple,AssemblyPath)):
            return self.extend(other)
        elif not isinstance(other, (Placement, int)):
            return NotImplemented
        if isinstance(other, int):
            if not len(self):
                raise TypeError("Can't interpret comp., index without a path")

            # will raise IndexError if other is out of range
            other = self[-1].component.components[other]
        
        elif len(self):
            # make sure these line up
            self[-1].component.components.index(other)

        # we've passed all the checks, so go ahead
        super().append(other)

    # do I need to override extend?
    def __add__(self, other):
        newpath = copy.copy(self)
        newpath.append(other)
        return newpath
    
    def todict(self):
        if not self:
            return []
        return [self[0].parent] + [p.parent.components.index(p)
                                   for p in self]
        
    @classmethod
    def construct(self, path):
        """Construct an AssemlyPath from the compact `todict` output"""
        if not path:
            return AssemblyPath()
        res = AssemblyPath([path[0].components[path[1]]])
        for index in path[2:]:
            res.append(index)
        return res
        
        
class SimDataMatch(Mappable):
    """Translate a request for simulation data for a spec placed in the 
    Assembly tree into a full SimulationsDB query and attach matching
    datasets if found
    
    Args:
        assemblyPath (AssemblyPath):
                              Path from assembly root to component which "owns"
                              the specs, ordered from branch to leaf
        spec (EmissionSpec): Reference to the relevant spec with non-zero 
                              emission rate
        query:    The full query built from the requests' inputs
        weight (float): additional weighting applied to this query
                        E.g., neutrons per decay of U238
        dataset:  List of simulation datasets matching the full query
        livetime: Effective livetime of these datasets compared to the 
                  emissionrate of the request
        status (str): space-separated list of status tags. Will be used as 
                      html classes for web interface
        rawerate (Quantity): Emission rate for this spec before `weight`
    """
    def __init__(self, assemblyPath=None, spec=None, query=None, weight=1,
                 dataset=None, livetime=None, status=None, rawerate=None, 
                 **kwargs):
        super().__init__(**kwargs)
        self.assemblyPath = assemblyPath or AssemblyPath()
        self.spec = spec
        self.query = query
        self.weight = weight
        self.dataset = dataset
        self.livetime = ensure_quantity(livetime, "year")
        self.status = status or ""
        self._rawerate = ensure_quantity(rawerate, "1/day")

    @property
    def emissionrate(self):
        if self._rawerate is None:
            #calculate and cache
            pweight = self.assemblyPath.weight
            if (pweight is not None
                and hasattr(self.spec, 'emissionrate')):
                self._rawerate = pweight*self.spec.emissionrate(self.component)
        if self._rawerate is not None and self.weight is not None:
            return self._rawerate * self.weight

        # if we get here, can't calculate
        return None
        
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
    
    def hasstatus(self, tag):
        """Is `tag` a full, space-separated word in our list of tags?"""
        return tag in self.status.split()
        

    def __eq__(self, other):
        try:
            return (self.assemblyPath == other.assemblyPath
                    and self.spec == other.spec
                    and self.query == other.query
                    and self.dataset == other.dataset
                    and self.weight == other.weight
                    and self.livetime == other.livetime)
        except AttributeError:
            return False
        
    def getquerymods(self):
        """Get a list of all querymods for this assemblyPath and spec"""
        # querymods can be attached to Components, Placements, MaterialSpecs, 
        # and BoundSpecs

        result = []
        if not self.assemblyPath or not self.spec:
            return result
        
        # order of low precedence is parent, child, placement, spec, boundspec
        # first all the components/placements
        for i, placement in enumerate(self.assemblyPath):
            #only get parent on first placement, since it is 'child' on others
            if i==0 and placement.parent.querymod:
                result.append(placement.parent.querymod)
            if placement.component.querymod:
                result.append(placement.component.querymod)
            if placement.querymod:
                result.append(placement.querymod)
            
        # find the BoundSpec this spec belongs to
        for bs in self.component.specs:
            if (bs.spec == self.spec.getrootspec()):
                if bs.spec.querymod:
                    result.append(bs.querymod)
                if bs.querymod:
                    result.append(bs.querymod)
                #should only appear once. I think?
                break
        
        return result
    
    @property
    def component(self):
        return self.assemblyPath[-1].component if self.assemblyPath else None
        
    def clone(self, query=None, weight=None, dataset=None, livetime=None):
        """Overload `Mappable.clone` to provide the things that should change"""
        newmatch = super().clone()
        if query is not None:
            newmatch.query = query
        if weight is not None:
            newmatch.weight = weight
        if dataset is not None:
            newmatch.dataset = dataset
        if livetime is not None:
            newmatch.livetime = ensure_quantity(livetime, "year")
        return newmatch

    def todict(self):
        mydict = copy.copy(self.__dict__)
        return to_primitive(mydict)

    
def buildmatchfromdict(args):
    """Create a match from a dict. Dummy wrapper to match format of 
    components and specs
    Args:
        args (dict): dictionary created by `todict`
    Returns:
        new SimDataMatch object
    """
    return SimDataMatch(**args)
