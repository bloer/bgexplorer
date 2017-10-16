"""
@file bgmodel.py
@author: bloer

Defines the BgModel class, which collects metadata about a model definition. 
The main purpose of this class is to aid in importing/exporting a complex
model to a bare dict. 
"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
#from builtins import super

import copy
import uuid

from .component import buildcomponentfromdict, Assembly
from .compspec import buildspecfromdict

class BgModel(object):
    def __init__(self, name=None, assemblyroot=None, 
                 version=0, description='',
                 derivedFrom=None, editDetails=None,
                 components=None, specs=None,
                 sanitize=True):
        """Store additional info about the model for bookeeping. 
        Params:
            assemblyroot (Assembly): top-level Assembly defining entire model
            name (str): a short name for the model to be used as an identifier
            version (int): version number for name
            description (str): brief description of the model contents
            derivedFrom: a reference to the parent or predecessor that was the 
                base for this model, assuming it is an edit of a prior version
            editDetails (dict): metadata about the most recent edit 
                (e.g. username, date, comment); 
            components (dict): dictionary mapping IDs to components
            specs (dict): dictionary mapping IDs to CompSpecs
            sanitize(bool): add cross references, etc to model on creation
        """
        
        self.name = name 
        self.assemblyroot = assemblyroot or Assembly(self.name)
        self.version = version
        self.description = description 
        self.derivedFrom = derivedFrom
        self.editDetails = editDetails or {}
        self.components = components or {}
        self.specs = specs or {}
        if sanitize:
            self.sanitize()
        

    @property
    def id(self):
        return getattr(self,'_id')
        
    def registerobject(self, obj, registry):
        """ Make sure that obj has an _id attribute and add it to registry
        """
        if not hasattr(obj,'_id'):
            obj._id = str(uuid.uuid4())
        if obj._id not in registry:
            registry[obj._id] = obj
        elif registry[obj._id] != obj:
            print(("Error trying to register object with name %s;", 
                   "component with ID %s already registered!")
                   %(getattr(obj,'name',''), obj._id))
            #now what? 
            raise ValueError(obj._id)
        
    def get_unplaced_components(self, toponly=True):
        """Get a list of all components not placed into any assembly
        Args:
            toponly(bool): If true, return only top-level components 
                with no placements. Otherwise, return all components
                that are not a descendent of assemblyroot"""
        res = [comp for comp in self.components.values()
               if not self.assemblyroot.isparentof(comp, deep=True)]
        if toponly:
            res= [comp for comp in res  if not comp.placements]

        return res
    
    def sanitize(self, comp=None):
        """Make sure that all objects are fully built and registered"""

        if not comp:
            comp = self.assemblyroot

        self.connectreferences(comp)

        
        #make sure that this component has an ID and is in the registry
        self.registerobject(comp, self.components);
        #if the component has CompSpecs, register them too
        #also make sure the reverse reference to owned component exists
        for spec in comp.findspecs(deep=False):
            self.registerobject(spec, self.specs)
            #todo: should we use weakrefs instead? 
            spec.appliedto.add(comp)

        #now recurse for subcomponents in assembly
        if hasattr(comp, '_components'):
            for placement in comp._components:
                #these should both be true already:
                placement.parent = comp 
                placement.component.placements.add(placement) 
                self.sanitize(placement.component)

        #miscellaneous checks
        #make sure that the assemblyroot is marked
        if comp is self.assemblyroot:
            #make sure unplaced components are handled too
            for comp in self.get_unplaced_components():
                self.sanitize(comp)
                    

    @staticmethod
    def pack(obj):
        res = obj.todict()
        res.pop('_id',None)
        return res
        
    def todict(self, sanitize=True):
        """Export all of our data to a bare dictionary that can in turn be 
        exported to JSON, stored in a database, etc
        """
        
        #first make sure all objects are registered and built sanely
        if sanitize:
            self.sanitize()
        
        #now convert all objects to dicts, and all references to IDs
        result = copy.copy(self.__dict__)

        result['assemblyroot'] = self.assemblyroot._id
        result['specs'] = \
        {key: self.pack(spec) for key, spec in self.specs.items()}
        result['components'] = \
        {key: self.pack(comp) for key, comp in self.components.items()}

        return result

    def connectreferences(self, comp):
        """ transform ID references in an exported component to actual objects
        """
        comp.specs = [self.specs.get(key,key) for key in comp.specs]
        for p in getattr(comp, '_components', []):
            p.component = self.components.get(p.component, p.component)
            if hasattr(p.component,'placements'):
                p.component.placements.add(p) #probably redundant, but harmless
            
    
    @classmethod
    def buildfromdict(cls, d):
        """ Construct a new BgModel from a dictionary. It's assumed that 
        the dict d was generated from the todict method previously
        """
        #handle mongo inserting _ids (or should I just make this mappable?)
        _id = d.pop('_id', None)
        model = cls(**d, sanitize=False)
        if _id:
            model._id = _id

        #now we need to construct specs and components from their objects
        #this does not convert ID references to objects!
        for key, spec in model.specs.items():
            spec['_id'] = key
            model.specs[key] = buildspecfromdict(spec)
        for key, comp in model.components.items():
            comp['_id'] = key
            model.components[key] = buildcomponentfromdict(comp)
                
        #update the assemblyroot to the actual object
        model.assemblyroot = model.components[model.assemblyroot]
        
        #just to make sure
        model.sanitize()

        return model
    
        
        

    
