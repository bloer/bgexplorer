# -*- coding: utf-8 -*-
"""
Created on Mon Aug 10 08:22:25 2015

@author: bloer
"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super

from .common import units, ensure_quantity, removeclasses
from .mappable import Mappable

from collections import OrderedDict
from copy import copy
import logging
log = logging.getLogger(__name__)

#utility function for selections
def selectany(comp=None, spec=None):
    return True


class BoundSpec(object):
    """Represents a spec bound to a component with querymods.
    Args:
        spec (EmissionSpec): Spec to attach to component
        querymod:  Additional info for simulationsDB matching
        simdata:   List of SimDataRequest objects for binding simulation 
                   data to spec's subspecs
    """
    def __init__(self, spec=None, querymod=None):
        self.spec = spec
        self.querymod = querymod 
                
    def __eq__(self, other): 
        if hasattr(other, 'spec'):
            return self.spec == other.spec
        return self.spec == other
        
    def todict(self):
        return dict(
            spec = self.spec,
            querymod = self.querymod,
        )
        
    @classmethod
    def _childattr(cls, attr):
        """Create an attribute for this class that refers to child"""
        def get(self):
            return getattr(self.spec,attr,None)

        setattr(cls, attr, property(get))
    
    _copyattrs = ('name','distribution','category','rate','getratestr','id')
    
for attr in BoundSpec._copyattrs:
    BoundSpec._childattr(attr)
    
    

class BaseComponent(Mappable):
    """Base class for Components and Assemblies, defines useful functions"""
    def __init__(self, name=None, description=None, 
                 comment=None, moreinfo=None, 
                 specs=[], querymod=None, **kwargs) : 
        """Create a new BaseComponent.
        Args:
            name (str): a short, hopefully unique name for the component
            description (str): longer descriptive string
            comment (str): describe current implementation or status
            moreinfo (dict): dictionary of additional metadata
            specs (list): EmissionSpecifications attached to this component
                Each item in the list may be either a EmissionSpecification 
                or a (EmissionSpecification, querymod) pair
            querymod (dict): modify the default query to find ConversionEffs
                for all specs associated with this component. See the 
                specific DB implementation for the expected format
        """
        super().__init__(**kwargs)
        self.name = name
        self.description = description
        self.comment = comment
        self.moreinfo = moreinfo or {}
        self.placements = set()
        #basic bookkeeping and descriptive stuff
        self.querymod = querymod 
        self.specs = specs
        

    @property
    def specs(self):
        return self._specs

    @specs.setter
    def specs(self, newspecs):
        self._specs = []
        for spec in newspecs:
            if isinstance(spec, (tuple, list)):
                self.addspec(*spec)
            else:
                self.addspec(spec)

    def __str__(self):
        return "%s('%s')"%(type(self).__name__, self.name)
    
    def __repr__(self):
        return "%s('%s')"%(type(self).__name__, self.id)
    
    def clone(self, newname=None):
        myclone = super().clone(newname, deep=False)
        # make new boundspec objects, remove simdata hits
        myclone.specs = [copy(spec) for spec in self.specs]
        myclone.placements = set()
        return myclone
        
    def addspec(self, spec, querymod=None, index=None):
        if index is None:
            index = len(self.specs)
        if isinstance(spec, dict):
            spec = BoundSpec(**spec)
        elif isinstance(spec, BoundSpec):
            pass
        else:
            spec = BoundSpec(spec,querymod)

        if hasattr(spec, 'appliedto'):
            spec.appliedto.add(self)
        self._specs.insert(index, spec)
        return spec

    def delspec(self, spec):
        """Remove this spec from our reference. type(spec) can be a 
        EmissionSpec or index"""
        if type(spec) is int:
            #treat as index
            spec = self._specs[spec]
        self._specs.remove(spec)
        if hasattr(spec, 'appliedto'):
            spec.appliedto.remove(self)

    def getspecs(self, deep=False, children=False):
        """Find specs associated with this component. 
        Args:
            deep (bool): If False (default), only return top-level specs. 
                         Otherwise, also include subspecs 
            children (bool): If True and this component is an assembly, 
                             also include subcomponents
        """
        result = [bs.spec for bs in self._specs]
        if deep:
            #concatenate all subspecs
            result = sum((s.subspecs if hasattr(s,'subspecs') else [s]
                          for s in result), [])
        # can we assume they are unique?
        #return set(result) # this messes up order!
        return result
            
    def gettotalweight(self, fromroot=None):
        """Get the total weight (usually number of) placed components
        Will be 0 if not placed anywhere in tree or only belong to unplaced 
        assemblies
        Args:
            fromroot (Assembly): only count weight belonging to this assembly
                                 If None, count all weights
        """
        if not self.placements: #we are a root component
            if fromroot is None or fromroot is self:
                return 1
            else:
                return 0
        else:
            return sum([p.gettotalweight(fromroot) for p in self.placements])

    def passingselector(self, selector=None):
        """
        Get a list of all component specifications that pass the given selector
        Args:
            selector(function): accepts a Component and EmissionSpecification
                                and returns true or false
        Returns:
            passing (list): list of (component, spec, weight) tuples that
                            pass the selector function 
                            (for leaf components comp==self and weight==1)
        """
        if not selector:
            selector = selectany
        return [(self,s,1) for s in self.getspecs(deep=True) 
                if selector(self,s)]
    
    def isparentof(self, component, deep=False):
        """ Are we the parent component? This is a leaf, so only if it is us """
        return component is self
    
    def getcomponents(self, deep=False, withweight=False, merge=True):
        """Get list of subcomponents. Makes it easier to do things recursively
        on assembly trees if all components have this function
        """
        return []


    def getstatus(self):
        result = ""
        #first make sure all our specs give the right units
        for spec in self.getspecs(deep=True):
            try:
                spec.emissionrate(self).to('1/s')
            except units.errors.DimensionalityError:
                result += (" DimensionalityError: emissionrate spec for '{}'({}) "
                           .format(spec.name, spec.id))

        return result
    
    def todict(self):
        """Export this object to a dictionary suitable for storage/transmission
        """
        result = removeclasses(copy(self.__dict__))
        result['__class__'] = type(self).__name__
        #placements may not have IDs, so delete and assume they'll be rebuilt
        del result['placements']
        return result
        
class Component(BaseComponent):
    """Helper class to store list of component physical parameters

    All dimensional parameters will be cast to pint.Quantity's if bare numbers 
    are passed, with default SI units (kg, m, s). 
    All attributes are optional 
    
    Attributes: are same as init args
    

    """
    def __init__(self, name=None, material=None, mass=None, volume=None,
                 surface=None, surface_in=None, surface_out=None,
                 surface_interior=None, **kwargs):
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
                Note: Not actually used in forms!!!
        """
        super().__init__(name=name, **kwargs)
        self.material = material
        self.mass = mass or 0*units.kg
        self.volume = volume or 0*units.cm**3
        self.surface_in = surface_in or 0*units.cm**2
        self.surface_out = surface_out or 0*units.cm**2
        self.surface_interior = surface_interior or 0*units.cm**2
        #allow surface to be a proxy for surface_out
        if surface and not surface_in and not surface_out:
            self.surface_out = surface

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
    

        
class Placement(object):
    """A class representing an instance of a component placed within an 
    Assembly. For example, the same resistor might be used in different places
    in an experiment, and so will need to be associated to different simulation
    datasets. This lets us avoid copying components. 
    """
    # TODO: give placements names!
    def __init__(self, parent=None, component=None, weight=1, querymod=None,
                 name=None):
        """Args:
            parent (Assembly): assembly in which we're being placed
                Unlike components, placements should be unique
            component (Component): the component or assembly to place here
            weight (numeric): Usually, how many of this component, but could 
                be fractional in some cases
            querymod (dict): modifier to DB query to locate sim datasets
            name (str): Name associated with this particular placement. By 
                        default will adopt the name of the component
            
        """
        self.parent = parent
        self.component = component
        self.weight = weight
        self.querymod = querymod
        self._name = None
        self.name = name
        if hasattr(component, 'placements'): #it might still be a reference
            component.placements.add(self)

    def gettotalweight(self, fromroot=None):
        if not self.parent:
            parentweight = 1 if fromroot is None else 0
        else:
            parentweight = self.parent.gettotalweight(fromroot)
        return self.weight * parentweight

    @property
    def name(self):
        if self._name:
            return self._name
        return getattr(self.component, 'name', None)

    @name.setter
    def name(self, newname):
        if newname != getattr(self.component,'name',None):
            self._name = newname

    def todict(self):
        result = removeclasses(copy(self.__dict__))
        #don't save 'name' unless it is different from component
        if self.name == getattr(self.component,'name'):
            del result['name']
        #replace objects with ID references
        del result['parent'] #this gets reset on construction
        return result

    def tocompact(self):
        """Reduce this to a referenceable form"""
        try:
            pid = self.parent.id
        except:
            pid=None
        try:
            index = self.parent.components.index(self)
        except:
            index=None

        return (pid, index)
        


class Assembly(BaseComponent):
    """Assembly of multiple components"""
    def __init__(self, name=None, components=[], **kwargs):
        """Create a new assembly of multiple components
        
        Args:
            components (list): list of Components or Assemblies owned by this
                object. Can be bare Components or tuples, dictionary of
                Placement arguments.
        """
        super().__init__(name=name, **kwargs)

        self.components = components

    #methods to set components (mostly from a form)
    @property
    def components(self):
        return self._components #should I return by copy here?

    @components.setter
    def components(self, components):
        """construct the list of components from list of comps or (comp,weight) 
        pairs. Can also be bare objects
        """
        self._components = []
        for comp in components:
            self.addcomponent(comp)

    def clone(self):
        myclone = super().clone()
        myclone.components = [copy(plcmnt) for plcmnt in self.components]
        return myclone 

    def addcomponent(self, placement, index=None):
        """Add a new component directly to this assembly
        the argument "placement" can take many forms: 
           Component/Assembly to attache
           list or tuple of positional arguments to Placement
           dict of kwarg arguments to Placement
        index indicates the insertion point
        """
        if isinstance(placement, BaseComponent):
            placement = Placement(self, placement)
        elif isinstance(placement, Placement): 
            placement.parent = self
        elif type(placement) in (tuple, list):
            placement = Placement(self, *placement)
        elif isinstance(placement, dict):
            if 'component' not in placement:
                compdict = {'name':placement.pop('name',"<new>"),
                            '__class__': placement.pop('__class__','Component')}
                placement['component'] = buildcomponentfromdict(compdict)
            placement = Placement(self, **placement)
        else:
            raise TypeError("Unhandled type %s for placement",type(placement))
        if index is None:
            index = len(self._components)
        self._components.insert(index, placement)

    def delcomponent(self, comp):
        """Delete a subcomponent. comp can take a few forms:
           ComponentAssembly owned
           Placement
           index
        """
        before = len(self._components)
        if isinstance(comp, Placement) and comp in self._components:
            self._components.remove(comp)
        elif isinstance(comp, BaseComponent):
            for index, placement in enumerate(self._components):
                if placement.component == comp:
                    del self._components[index]
                    break
        elif type(comp) is int:
            del self._components[comp]
        if len(self._components) != before-1:
            log.warning("Unable to delete component %s", comp)
            
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
            return [(p.component, p.weight) if withweight else p.component 
                    for p in self._components]
        allcomp = []
        for placement in self._components:
            comp, weight = placement.component, placement.weight
            if hasattr(comp,'components'):
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

    def getchildweight(self, child, deep=False):
        """Get the total weight of child component"""
        return sum(w for c,w in self.getcomponents(deep=deep, 
                                                   withweight=True,
                                                   merge=True)
                   if c==child)
        
    def isparentof(self, component, deep=False):
        """Is this component within our owned tree?"""
        if component is self:
            return True
        for sub in self.getcomponents(deep=False):
            if sub == component:
                return True
            if deep and sub.isparentof(component, deep=deep):
                return True
        return False
    
    def passingselector(self, selector=None):
        """ Override leaf-level method to add component weights """
        if not selector:
            selector = selectany
        #if the selector passes for us, it passes for all children
        ##this makes really confusing logic for negation!!!!
        #try:
        #    if selector(self,None):
        #        selector = selectany
        #except:
        #    #interpret exception as not wanting a None type so ignore
        #    pass
        
        #loop through children
        passing = []
        for comp, weight in self.getcomponents(withweight=True, deep=False):
            childpass = comp.passingselector(selector)
            passing.extend([(c,s,w*weight) for c,s,w in childpass])
        return passing
    
    def gethierarchyto(self,component, placements=False):
        """Find how this component is related to a parent
        Returns None if component can not be reached or a list of tuples
        containing all possible routes. 
        If `placements` is True, return tuple of placements instead of 
        components. 
        """
        if not self.isparentof(component,deep=True):
            return None
        result = []
        tree = tuple() if placements else (self,)
        for placement in self.components:
            subcomp = placement.component
            mytree = tree+(placement if placement else subcomp,)
            if subcomp is component:
                result.append(mytree)
            elif subcomp.isparentof(component, deep=True):
                for subtree in subcomp.gethierarchyto(component, placements):
                    result.append(mytree+subtree)
        return result
        
    def getspecs(self, deep=False, children=False):
        result = super().getspecs(deep=deep)
        
        if children:
            for comp in self.getcomponents(deep=True, withweight=False):
                result.extend(comp.getspecs(deep=deep, children=children))
        # may have overlaps, so need to filter
        return set(result)
    
    @property
    def material(self):
        return None

    #there has got to be a smarter way to do all of this...
    def sumoverchildren(self,attr):
        """Utility function to ease the overrides below"""
        return sum(c.__getattribute__(attr)*w 
                   for c,w in self.getcomponents(withweight=True, deep=False))

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

    
        
        
def buildcomponentfromdict(args):
    """Construct a Component or Assembly from a dict"""
    classname = args.pop('__class__',None)
    cls = Component
    if 'components' in args:
        cls = Assembly
    elif classname:
        if classname == 'Assembly':
            cls = Assembly
        elif classname != 'Component':
            raise ValueError("buildcomponentfromdict: Unknown class name '%s'"
                             %classname)
    return cls(**args)


