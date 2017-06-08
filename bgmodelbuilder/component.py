# -*- coding: utf-8 -*-
"""
Created on Mon Aug 10 08:22:25 2015

@author: bloer
"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

from . import units

from collections import namedtuple, OrderedDict
from copy import copy

#utility function for selections
def selectany(comp=None, spec=None):
    return True


def ensure_quantity(value, defunit):
    """Make sure a variable is a pint.Quantity, and transform if unitless
    
    Args:
        value: The test value
        defunit (str,Unit, Quanty): default unit to interpret as
    Returns:
        Quantity: Value if already Quantity, else Quantity(value, defunit)
    """
    if value is None:
        return None
    qval = units.Quantity(value)
    if qval.dimensionality != units.Quantity(defunit).dimensionality:
        if qval.dimensionality == units.dimensionless.dimensionality:
            qval = units.Quantity(qval, defunit)
        else:
            except units.DimensionalityError(qval.u, defunit)
    
    return qval
    
    

class PhysicalParameters(object):
    """Helper class to store list of component physical parameters

    All dimensional parameters will be cast to pint.Quantity's if bare numbers 
    are passed, with default SI units (kg, m, s). 
    All attributes are optional 
    
    Attributes: are same as init args
    

    """
    def __init___(self, material=None, mass=None, volume=None,
                  surface=None, surface_in=None, surface_out=None,
                  surface_interior=None):
        """Constructor

        If `surface_in` or `surface_out` are given, `surface` is ignored
        
        Args:
            material (str): physical material (e.g. wood, copper)
            mass (Quantity): mass of material. interpreted as kg if unitless
            volume (Quantity): volume of material, interpreted as m^3
            surface (Quantity): total surface area. interpted as m^2  
            surface_in (Quantity): inner surface area (e.g. cryostat) 
            surface_out (Quantity): same as inner, but for outer surface
            surface_interior (Quantity): total covered area of pieces used to 
                construct a monolithic component e.g. bricks of lead
        """
            
        self._material = material
        self._mass = mass
        self._volume = volume
        self._surface_in = surface_in 
        self._surface_out = surface_out
        self._surface_interior = surface_interior
        #allow surface to be a proxy for surface_out
        if surface and not surface_in and not surface_in:
            self._surface_out = ensure_quantity(surface,'m^2')
            
        #getters
        @property
        def material(self):
            return self._material
        @property
        def mass(self):
            return self._mass        
        @property
        def volume(self):
            return self._volume
        @property
        def surface_in(self):
            return self._surface_in
        @property 
        def surface_out(self):
            return self._surface_out
        @property 
        def surface_interior(self):
            return self._surface_interior
        @property
        def surface(self):
            return self.surface_in + self.surface_out

        #setters, make sure they have units!
        @material.setter
        def material(self,material):
            self._material = material
        @mass.setter
        def mass(self, mass):
            self._mass = ensure_quantity(mass, 'kg')
        @volume.setter
        def volume(self, volume):
            self._volume = ensure_quantity(volume, 'm^3')
        @surface_in.setter
        def surface_in(self, surface_in):
            self._surface_in = ensure_quantity(surface_in, 'm^2')
        @surface_out.setter
        def surface_out(self, surface_out):
            self._surface_out = ensure_quantity(surface_out, 'm^2')
        @surface_interior.setter
        def surface_interior(self, surface_interior):
            self._surface_interior = ensure_quantity(surface_interior, 'm^2')
        


"""
Querymod operator
Modifies the query to associate simulation datasets to component,spec pairs

The exact form and implementation of each argument is up to the specific 
ConversionsDatabase used.  For example, for a MongoDB database, the 
arguments are objects that will directly modify the pymongo query object.

The operators are:
    override:  replace the default query
    union:     return the OR of this test and the default
    intersect: return the AND of this test and the default
    exclude:   return the difference (default AND NOT ) with this test

    override_keys
    union_keys
    intersect_keys
    exclude_keys


There are two types of operator: <op> and <op>_keys. <op> operators modify
the query as a whole, while <op>_keys modify individual keys of the query.

For example, assume the original query for a mongodb EffDB would be:
q0 = {'volume': component.name, 'distribution': spec.distribution}

QueryMod(union={'distribution':'bulk'}) would result in
q1 = {'$or': [q0, {'distribution':'bulk'}] }.

Whereas
QueryMod(union_keys={'distribution':'bulk'}) would give
q1 = {'volume': component.name, 'distribution':{'$or':[spec.distribution,
                                                       'bulk']} }
"""



class Component(PhysicalParameters):
    """Single piece of detector/shield geometry with set of material specs"""

    def __init__(self, name=None, description=None, 
                 comment=None, moreinfo=None, 
                 specs=None, querymod=None, **kwargs):
        """ Initialize a new physical component. 
        
        Args:
            name (str): name of this component, ideally unique
            description (str): one-sentence description of this component
            comment (str): detail about implementation (e.g. mass made up)
            moreinfo (dict): key-value pairs for any other information like 
                part numbers, vendor contacts, etc
            specs (list): ComponentSpecifications attached to this component
                Each item in the list may be either a ComponentSpecification 
                or a (ComponentSpecification, querymod) pair
            querymod (dict): modify the default query to find ConversionEffs
                for all specs associated with this component. See the 
                specific DB implementation for the expected format
        

        """
        #initialize the base class
        super().__init__(**kwargs)
        
        #basic bookkeeping and descriptive stuff
        self.name = name
        self.description = description
        self.comment = comment
        self.moreinfo = moreinfo or dict()
        self.querymods = dict()
        if querymod:
            self.querymods[None] = querymod
        self.specs = []
        for spec in specs:
            if type(spec) in [tuple, list]:
                self.addspec(*spec)
            else:
                self.addspec(spec)
        
            
    def __str__(self):
        return "Component('%s')"%self.name
    
    def export(self):
        """Extract all arguments needed for the constructor as a dictionary"""
        #need to do something smarter here...
        return self.__dict__
    
    def __repr__(self):
        return "Component(**%s)"%(self.export())
    
    @property
    def id(self):
        """unique, hopefully permanent ID"""
        return getattr(self,'_id',self.name)

    def getspecid(self,spec):
        """unique id for a component, spec combo"""
        if spec is None: #ALL specs associated to this component
            return self.id
        elif spec not in self.specs:
            return None
        return str(self.id)+'//'+str(getattr(spec,'id',self.specs.index(spec)))
    
    def addspec(self, spec, querymod=None):
        self.specs.append(spec)
        if querymod:
            self.querymods[spec] = querymod
            
    def getquerymod(self, spec=None):
        mymod = self.querymods.get(spec,{})
        if spec: #combine with the per-component spec
            base = copy(self.querymods.get(None, {}))
            base.update(mymod)
            mymod = base
        return mymod

    def findspecs(self, name, deep=False):
        return [a for a in self.specs if a.name == name]
    
    
    def passingselector(self, selector=None):
        """
        Get a list of all component specifications that pass the given selector
        Args:
            selector(function): accepts a Component and ComponentSpecification
                                and returns true or false
        Returns:
            passing (list): list of (component, spec, weight) tuples that
                            pass the selector function 
                            (for leaf components comp==self and weight==1)
        """
        if not selector:
            selector = passany
        return [(self,s,1) for s in self.specs if selector(self,s)]
    
    def isparentof(self, component, deep=False):
        """ Are we the parent component? This is a leaf, so only if it is us """
        return component is self

    
    
    
class Assembly(Component):
    """Assembly of multiple components"""
    def __init__(self,name=None, components=None, **kwargs):
        """Create a new assembly of multiple components
        
        Args:
            name (str): Name for this assembly (ideally unique)
            components (list): list of Components or Assemblies owned by this
                object. Can be bare Components or (Component, weight) pairs
        """
        super().__init__(name=name, **kwargs)

        self._subcompmap = dict()
        self.components[]

        #construct the list of components from list of comps or (comp,weight) 
        #pairs. Can also be bare objects
        for comp in components:
            c = comp
            w = 1
            if type(comp) in (tuple,list):
                c,w = comp
            if type(c) is dict:
                c=buildcomponent(**c)
            self.addcomponent(c,w)

        super().__init__(name=name,**kwargs)
        
    def __str__(self):
        return "Assembly('%s')"%self.name
    
    def export(self):
        """Extract all arguments needed for the constructor as a dictionary"""
        #need to do something smarter here...
        return self.__dict__
    
    def __repr__(self):
        return "Assembly(**%s)"%(self.export())
        
        
    def addcomponent(self,component, weight=1):
        """Add a new component directly to this assembly"""
        self.components.append((component,weight))
        if component.name:
            self._subcompmap[component.name] = (component,weight)
            
    #functions for inspecting the tree of subcomponents
    def getcomponents(self, deep=False, withweight=False, merge=True):
        """Get all components belonging directly or indirectly to this assembly
        
        Args:
            deep (bool): if true, include components of nested Assemblies
            withweight (bool): if true, return a list of (comp,weight) pairs,
                otherwise return the bare list of components
            merge (bool): if true, rollup the weights of components that appear
                at multiple leaves in the tree
        """
        if not deep:
            return [c if withweight else c[0] for c in self.components]
        allcomp = []
        for comp,weight in self.components:
            if hasattr(comp,'getcomponents'):
                subcomps = comp.getcomponents(deep,withweight)
                if withweight:
                    subcomps=[(c,w*weight) for c,w in subcomps]
                allcomp.extend(subcomps)
            else:
                allcomp.append((comp,weight) if withweight else comp)
        if merge:
            temp = OrderedDict()
            for c in allcomp:
                comp, weight = c if withweight else (c,1)
                if comp not in temp:
                    temp[comp] = 0
                temp[comp] += weight
            allcomp = [(c,w) if withweight else c for c,w in temp.items()]
            
        return allcomp

    def isparentof(self, component, deep=False):
    """Is this component within our owned tree?"""
    return (component is self 
            or component in self.getcomponents(deep=deep, withweight=False))
    
    def passingselector(self, selector=None):
        """ Override leaf-level method to add component weights """
        if not selector:
            selector = selectany
        #if the selector passes for us, it passes for all children
        try:
            if selector(self,None):
                selector = selectany
        except:
            #interpret exception as not wanting a None type so ignore
            pass
        
        #loop through children
        passing = []
        for comp, weight in self.components:
            childpass = comp.passingselector(childselector)
            passing.extend([(c,s,w*weight) for c,s,w in childpass])
        return passing
    
    def gethierarchyto(self,component, includeroot=True, includeleaf=True):
        """Find how this component is related to a parent"""
        if not self.isparentof(component,deep=True):
            return None
        tree = [self] if includeroot else []
        for subcomp in self.getcomponents(deep=False):
            if subcomp is component:
                break
            elif hasattr(subcomp,'gethierarchyto'):
                subtree = subcomp.gethierarchyto(component, includeroot=True, 
                                                 includeleaf=False)
                if subtree:
                    tree.extend(subtree)
                    break
        if includeleaf:
            tree.append(component)
        return tree
        
    def findspecs(self, name, deep=False):
        res = set()
        for comp in self.getcomponents(deep=deep, withweight=False):
            set.update(comp.findspecs(name=name, deep=deep))

    def assignids(self, root='/', override=True):
        """Assign a unique ID to each component based on the path to root.
        If override is False, components will keep any already-assigned IDs
        """
        if override or not hasattr(self,'_id'):
            self._id = root+self.name
        subroot=self._id+'/'

        for comp in self.getcomponents(deep=False, wighweight=False):
            if hasattr(comp,'assignids'):
                comp.assignids(subroot, override=override)
            else if override or not hasattr(comp, '_id'):
                comp._id = subroot+comp.name
    


    @property
    def material(self):
        return None

    #there has got to be a smarter way to do all of this...
    def sumoverchildren(self,attr):
        """Utility function to ease the overrides below"""
        return sum(c.__getattribute__(attr)*w for c,w in self.components)

    @property
    def mass(self):
        return self.sumoverchildren('mass')        
    @property
    def volume(self):
        return self.sumoverchildren('volume')
    @property
    def surface_in(self):
        return self.sumoverchildren('surface_in')
    @property 
    def surface_out(self):
        return self.sumoverchildren('surface_out')
    @property 
    def surface_interior(self):
        return self.sumoverchildren('surface_interior')
    @property
    def surface(self):
        return self.sumoverchildren('surface')

    
        
        
def buildcomponent(args):
    """Construct a Component or Assembly from a dict"""
    cls = Component
    if '__class__' in args:
        classname = x.pop('__class__')
        if classname == 'Assembly':
            cls = Assembly
        elif classname != 'Component':
            print("Unknown class name '%s'"%classname)
    return cls(**args)
