# -*- coding: utf-8 -*-
"""
Created on Mon Jul 27 11:04:32 2015

@author: bloer
"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super

from math import log,exp
from .common import units, ensure_quantity, removeclasses
from .mappable import Mappable
from copy import copy




class ComponentSpec(Mappable):
    """ Define a specification to determine emissions from some component.
    
    Each component will define a list of specs mapping to one or more
    simulated conversion efficiencies. Each spec has a 'primary' control
    (e.g., hours exposure for cosmogenic activation) from which a
    'susceptibility' is defined when combined with the conversion eff.
    
    Usually rates will be specified per unit mass or area, but if the optional
    parameter 'per_piece' is set to true, the 'raw' rate will be used
    
    Sub-classes should override the get_rate and get_susceptibility methods.    
    """

    #have a finite list of allowed distribution types
    _distribution_types = ("bulk","surface","surface_in","surface_out", 
                           "flux", "none")
    _default_distribution = "bulk"
        
    def __init__(self, name="",
                 distribution=_default_distribution, normfunc=None,
                 category="", comment="", reference="", moreinfo=None,
                 appliedto=None,
                 **kwargs):
        """Make a new ComponentSpec

        Args:
            name (str): Usually the name of the isotope
            distribution (str): how is the contaminant distributed? Most common
                values are bulk, surface_in, surface_out
            normfunc (func): A function taking the owning Component that returns
                a custom normalization factor. Can be a function taking a 
                component as argument or a string to be evaluated; in this 
                case the variable MUST be named 'component'. The special string
                'piece' is equivalent to '1'. The 'units' object is also 
                available to the string. 
            category(str): A descriptive category for higher-order groupings. 
                for example, Cosmogenic Activation, Radon Daughter
            comment (str) A descriptive comment
            reference (str) information about the origin of the number
            moreinfo (dict): key-value pairs for any other information
            appliedto (set): set of components this spec is bound to
        """
        super().__init__(**kwargs)

        self.name = name
        self.distribution = distribution
        #make sure distribution is valid
        if distribution not in self._distribution_types:
             print("Unknown distribution %s for ComponentSpeci %s; using '%s'"
                    %(distribution,name,self._default_distribution))
             distribution = self._default_distribution

        self.normfunc = normfunc

        self.category = category or type(self).__name__
        self.comment = comment
        self.reference = reference
        self.moreinfo = moreinfo or {}
        self.appliedto = appliedto or set()
        
    def __str__(self):
        return "%s('%s')"%(type(self).__name__, self.name)
        
    def __repr__(self):
        return ("ComponentSpec('%s',distribution='%s',category='%')"
                %(self.name, self.distribution, self.category))
        
    def getcomment(self):
        comment = ''
        if self.comment:
            comment += self.comment+" "
        if self.reference:
            comment += "Reference: "+self.reference
        return comment
        
    #subclasses should override
    def getfullspec(self):
        return ''
        
    @property
    def rate(self):
        """Get the unnormalized emission rate from this source"""
        return 0
        
    def getratestr(self):
        return str(self.rate.to_base_units().to_compact())
    
    #concrete classes _should_ override this moethod
    def emissionrate(self,component):
        """Normalize the emission rate to the component"""
        multiplier = 0
        if self.normfunc:
            if callable(self.normfunc): #its a function
                multiplier = self.normfunc(component)
            elif type(self.normfunc) is str:
                #evaluate it. the __builtins__ thing somewhat protects 
                #against malicious stuff. 
                multiplier = eval(self.normfunc, 
                                  {'__builtins__':{},'units':units},
                                  {'component':component, 'piece':1})
            else:
                raise TypeError("Unknown type %s for normfunc"%self.normfunc)
        else:
            multiplier = {
                "bulk": component.mass,
                "surface" : component.surface,
                "surface_in": component.surface_in,
                "surface_out": component.surface_out,
                "volumetric": component.volume,
                "volume": component.volume,
                "flux": component.surface_out,
            }.get(self.distribution,1)
        if multiplier is None:
            multiplier = 0

        return (self.rate * multiplier).to('1/s')
    
    def totalemissionrate(self):
        """Get the total emission rate from all associated components 
        and their global weights
        """
        return sum(self.emissionrate(comp) * comp.gettotalweight() 
                   for comp in self.appliedto)
    
    def todict(self):
        """Export this instance to a plain object"""
        result = copy(self.__dict__)
        #all 'appliedto' will get rebuilt on restore
        del result['appliedto']
        result['__class__'] = type(self).__name__
        return removeclasses(result)
        

class CombinedSpec(ComponentSpec):
    """Utility class to group multiple material specs into one"""
    
    def __init__(self,name="",specs=None,**kwargs):
        super().__init__(name=name, **kwargs)
        self._specs=[]
        if specs:
            for spec in specs:
                self.addmaterialspec(spec)
        
    @property
    def rate(self):
        return sum(spec.rate for spec in self._specs)
    
    def emissionrate(self,component):
        return sum(spec.emissionrate(component) for spec in self._specs)
        
    def getsubspecs(self):
        return self._specs
    
    def addmaterialspec(self,spec):
        #todo: is this really a good plan??
        spec._id = self.id+('-%d'%len(self._specs))
        spec.appliedto = self.appliedto 
        self._specs.append(spec)
        
    def __repr__(self):
        return "CombinedSpec('%s', specs=%s)"%(self.name, self._specs)

    def updatesubspecs(self, attr, val):
        for sub in self.getsubspecs():
            setattr(sub, attr, val)

    #overload __getitem__ so we can unpack subspecs directly
    #should we allow deep unpacking???
    def __getitem__(self,key):
        return self.getspecs()[key]

    
        

class RadioactiveIsotope(object):
    def __init__(self,halflife,name=None):
        self.halflife = ensure_quantity(halflife, units.seconds)
        self.name = name        

class RadioactiveContam(ComponentSpec):
    """ Spec for a (long-lived) radioactive isotope.
    
    The specification is defined by the isotope name, the distribution 
    (bulk, surface, surface_in or surface_out), and the decay rate in mBq/kg
    for bulk surfaces or mBq/cm2 for surface sources. 
    
    """

    def __init__(self, name='', rate=None, isotope=None, **kwargs):
        self._rate = ensure_quantity(rate)
        self.isotope = isotope or name
        if isinstance(self.isotope, dict): #handle imports
            self.isotope = RadioactiveIsotope(**self.isotope)
        super().__init__(name=name, **kwargs)
        
    @property
    def rate(self):
        return self._rate

    def getfullspec(self):
        return self.getratestr()
     
    def __repr__(self):
        return "RadioactiveContam('%s',%s)"%(self.name,self.getratestr())

    
                                
    
class RadonExposure(RadioactiveContam):
    """Exposure of a surface to air with radon content
    
    The class assumes an essentially constant rate of Pb210 decay soon after 
    exposure. I.e. neither the "cooldown" nor counting/integration time is 
    large compared to the 22.3 year half-life of Pb210. 
    """
    _tau_pb210 = 22.3*units.year / log(2)    
    _tau_rn222 = 3.8 * units.day / log(2)
    _default_column_height = 10*units.cm
    
    def __init__(self,radonlevel, exposure,  
                 distribution='surface', name='Pb210',
                 column_height = _default_column_height, mode="free",
                 **kwargs):
        self.radonlevel = ensure_quantity(radonlevel,"Bq/m^3")
        self.exposure = ensure_quantity(exposure, units.day)
        self.column_height = ensure_quantity(column_height, units.cm)
        if mode not in ("free","trapped"):
            print("Uknown mode %s: using 'free'"%mode)
            mode="free"
        self.mode = mode
        super().__init__(name=name,isotope=kwargs.pop('isotope','Pb210'),
                         distribution=distribution,
                         **kwargs)
    
    @property                     
    def rate(self):
        """Get the rate in decays/time/surface area"""
        #should do a full differential equation, but Rn222 and Pb210 rates are
        #very different, so just be crude
        if self.mode is "trapped":
            #rn decays away during exposure
            R0 = (self.radonlevel * self.column_height * 
                  (1-exp(-self.exposure/self._tau_rn222)) * 
                  self._tau_rn222 / self._tau_pb210)
            return R0 * exp(-self.exposure/self._tau_pb210)
        else:
            return (self.radonlevel * self.column_height * 
                    (1-exp(-self.exposure / self._tau_pb210)))
    
        
    def getfullspec(self):
        return "%s, %s, %s"%(self.radonlevel, self.exposure, self.distribution)
    
    def __repr__(self):
        return "RadonExposure(%s)"%(self.getfullspec())
                                                         



class DustAccumulation(CombinedSpec):
    """Dust deposited onto a surface or into the bulk of a material.
    Users specify the type and concentration of radioactive contaminants
    in the dust, how the dust distribution is modeled, and the accumulation
    rate, mass per surface area or total mass

    Args:
        dustmass(Quantity): mass of dust, units should match distribution
            e.g. dimensionless for bulk, kg/cm2 for surface, or kg for per piece
        isotopes(list): list of RadioactiveContams with rates in Bq/kg 
            present in the dust
    """        
    def __init__(self, dustmass, isotopes, **kwargs):
        self.isotopes = isotopes
        specs = [ RadioactiveContam(**iso) if isinstance(iso, dict) else iso
                  for iso in self.isotopes ]
        name = kwargs.pop('name', 'Dust')
        super().__init__(name=name,specs=specs, **kwargs)
        self.dustmass = ensure_quantity(dustmass)
        #These should really be setters...
        for spec in self.getsubspecs():
            spec.category = self.category
            spec.normfunc = self.normfunc
            spec.distribution = self.distribution
            spec._rate *= self.dustmass


    def getfullspec(self):
        return "dustmass=%s"%self.dustmass
        
    #todo: implement setters for things we should override!
    def todict(self):
        #remove the 'specs' since those are rebuilt
        #todo: this is inefficienct since they're built then deleted...
        result = super().todict()
        del result['specs']
        return result        


class CosmogenicIsotope(RadioactiveIsotope):
    def __init__(self, halflife, activationrate, name=None):
        self.activationrate = ensure_quantity(activationrate, "1/kg/day")
        super().__init__(halflife, name)
        
        
class CosmogenicSource(RadioactiveContam):
    """Production of radioactive isotope within a material from cosmic rays
    
    Many of the cosmic-ray generated isotopes have short half-lives, so 
    we need to properly take into account both the cooldown and integration 
    time to average the background over.
    
    Because the activation rate has to be provided for this class to work, 
    it must be for a specific material.
    """
    
    def __init__(self,isotope,exposure=0,
                 cooldown=0,integration=0,**kwargs):
        """Constructor
        Args:
            isotope (CosmogenicIsotope): Isotope for a given material
            exposure (float): time exposed to sea-level equivalent CR flux
            cooldown (float): time kept underground after activation before 
                counting
            integration (float): time over which decay emissions are measured
        """
        if isinstance(isotope, dict): #handle imports
           isotope = CosmogenicIsotope(**isotope)
        name = kwargs.get('name',isotope.name)
        super().__init__(name=name, isotope=isotope, **kwargs)    
        self.exposure = ensure_quantity(exposure, units.day)
        self.cooldown = ensure_quantity(cooldown, units.day)
        self.integration = ensure_quantity(integration, units.year)
        
    
    @property
    def rate(self):
        """Get the average decay rate over the integation interval"""
        tau = self.isotope.halflife / log(2)
        if self.integration <= 0*units.day:
            self.integration = tau / 100
        R0 = self.isotope.activationrate * (1-exp(-self.exposure/tau))
        a = self.cooldown
        b = a + self.integration
        return R0 * (exp(-a/tau) - exp(-b/tau)) * tau/(self.integration)
   
    def getfullspec(self):
        return "exposure=%s, cooldown=%s, integration=%s" %\
        (self.exposure, self.cooldown, self.integration)

    def __repr__(self):
        return "CosmogenicSource(%s, %s)"%(self.name, self.getfullspec())
    

class CosmogenicActivation(CombinedSpec):
    """Multiple cosmogenically-activated isotopes that share exposure times"""
    def __init__(self,isotopes,exposure, cooldown=0, integration=0,
                 name="Cosmogenic Activation",**kwargs):
        specs = [ CosmogenicSource(iso) for iso in isotopes ]
        super().__init__(name=name,specs=specs,**kwargs)
        self.isotopes = [CosmogenicIsotope(**iso) if isinstance(iso, dict) 
                         else iso for iso in isotopes]
        self.min_halflife = min([iso.halflife for iso in self.isotopes])
        self.cooldown = cooldown
        self.exposure = exposure
        self.integration = integration
        
        
    @property
    def exposure(self):
        return self._exposure
    @exposure.setter
    def exposure(self, newexp):
        self._exposure = ensure_quantity(newexp, units.day)
        for spec in self._specs:
            spec.exposure = self._exposure
    
    @property
    def cooldown(self):
        return self._cooldown
    @cooldown.setter
    def cooldown(self, newcool):
        self._cooldown = max(ensure_quantity(newcool, units.day), 0*units.day)
        for spec in self._specs:
            spec.cooldown = self._cooldown
    
    @property
    def integration(self):
        return self._integration
    @integration.setter
    def integration(self, newint):
        self._integration = max(ensure_quantity(newint, units.year), 
                                self.min_halflife/100)
        for spec in self._specs:
            spec.integration = self._integration
    
    def getfullspec(self):
        return "exposure=%s, cooldown=%s, integration=%s" %\
        (self.exposure, self.cooldown, self.integration)
        
    def __repr__(self):
        return "CosmogenicActivation(%s)"%(self.getfullspec())
            
    def todict(self):
        result = super().todict()
        del result['specs']
        #this gets calculated automatically
        del result['min_halflife']
        return result
        
def buildspecfromdict(args):
    """Construct a ComponentSpec from an exported dictionary"""
    #todo: this is pretty crude and will probably break...
    return eval(args.pop('__class__'))(**args)
    

