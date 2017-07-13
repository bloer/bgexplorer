# -*- coding: utf-8 -*-
"""
Created on Mon Jul 27 11:04:32 2015

@author: bloer
"""

#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *
from math import log,exp
from . import units
from copy import deepcopy as copy
#from abc import ABCMeta, abstractproperty

#from conversioneff import RegionOfInterst,EvaluatedRegionOfInterst,ConversionEff



class ComponentSpec(object):
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
                 **kwargs):
        """Make a new ComponentSpec

        Args:
            name (str): Usually the name of the isotope
            distribution (str): how is the contaminant distributed? Most common
                values are bulk, surface_in, surface_out
            normfunc (func): A function taking the owning Component that returns
                a custom normalization factor. For example, if normfunc is None,
                bulk specs use component.mass
            category(str): A descriptive category for higher-order groupings. 
                for example, Cosmogenic Activation, Radon Daughter
            comment (str) A descriptive comment
            reference (str) information about the origin of the number
            moreinfo (dict): key-value pairs for any other information
        """
        super().__init__()

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
        
    def __str__(self):
        return "ComponentSpec('%s')"%self.name
        
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
            multiplier = self.normfunc(component)
        else:
            multiplier = {
                "per_piece": 1,
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
        #convert to seconds to make sure dimensions cancel out
        return (self.rate * multiplier).to('1/s')
    
        
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
        
    def getspecs(self, deep=False):
        if not deep:
            return self._specs
        allspecs = []
        #print("getting material spec for %s"%self.name)
        for spec in self._specs:
            #print("\trecursing into subspec %s"%spec.name)
            if isinstance(spec,CombinedSpec):
                allspecs.extend(spec.getmaterialspecs(deep=True))
            else:
                allspecs.append(spec)
        #print("Finished getting deep specs for %s"%self.name)
        return allspecs
    
    def addmaterialspec(self,spec):
        self._specs.append(spec)
        
    def __repr__(self):
        return "CombinedSpec('%s', specs=%s)"%(self.name, self._specs)

    #overload __getitem__ so we can unpack subspecs directly
    #should we allow deep unpacking???
    def __getitem__(self,key):
        return self.getspecs()[key]

        

class RadioactiveIsotope(object):
    def __init__(self,halflife,name=None):
        self.halflife = halflife
        self.name = name        

class RadioactiveContam(ComponentSpec):
    """ Spec for a (long-lived) radioactive isotope.
    
    The specification is defined by the isotope name, the distribution 
    (bulk, surface, surface_in or surface_out), and the decay rate in mBq/kg
    for bulk surfaces or mBq/cm2 for surface sources. 
    
    """

    def __init__(self, name='', isotope=None, rate=None, **kwargs):
        self._rate = rate
        self.isotope = isotope or name
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
        self.radonlevel = radonlevel
        self.exposure = exposure
        self._column_height = column_height
        if mode not in ("free","trapped"):
            print("Uknown mode %s: using 'free'"%mode)
            mode="free"
        self.mode = mode
        super().__init__(name=name,isotope='Pb210',
                         distribution=distribution,
                         **kwargs)
    
    @property                     
    def rate(self):
        """Get the rate in decays/time/surface area"""
        #should do a full differential equation, but Rn222 and Pb210 rates are
        #very different, so just be crude
        if self.mode is "trapped":
            #rn decays away during exposure
            R0 = self.radonlevel * self._column_height * \
                (1-exp(-self.exposure/_tau_rn222)) * \
                _tau_rn222 / self._tau_pb210
            return R0 * exp(-self.exposure/self._tau_pb210)
        else:
            return self.radonlevel * self._column_height * \
                (1-exp(-self.exposure / self._tau_pb210))
    
        
    def getfullspec(self):
        return "%s, %s, %s"%(self.radonlevel, self.exposure, self.distribution)
    
    def __repr__(self):
        return "RadonExposure(%s)"%(self.getfullspec())
                                                         
        
#this class doesn't really add anything, but might help for accounting
class DustAccumulation(RadioactiveIsotope):
    """Dust deposited onto a surface or into the bulk of a material.
    Users specify the type and concentration of radioactive contaminants
    in the dust, how the dust distribution is modeled, and the accumulation
    rate, mass per surface area or total mass
    """        
    def __init__(self, isotope, dustmass, concentration, **kwargs):
        """Args:
            dustmass (float): dimensioned mass of dust considered
                Units should follow the 'distribution', i.e. /area if surface, 
                or per mass if bulk. Otherwise provide an apporpraite normfunc
            concentration (float): decay rate of the isotope per dust mass
                note that ppb_U, ppb_Th, and ppb_K are defined in units
        """
        super().__init__(name="Dust (%s)"%isotope, isotope=isotope,**kwargs)
        self.dustmass = dustmass
        self.concentration = concentration

        def getfullspec(self):
            return "%s, %s"%(self.dustmass,self.concentration)

        def __repr__(self):
            return "DustAccumulation(%s, %s)"%(self.isotope,self.getfullspec())

        @property
        def rate(self):
            return self.dustmass * self*concentration


class CosmogenicIsotope(RadioactiveIsotope):
    def __init__(self, halflife, activationrate, name=None):
        self.activationrate = activationrate
        super().__init__(halflife, name)
        
        
class CosmogenicActivation(RadioactiveContam):
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
            cooldown (float): time kept underground after activation before counting
            integration (float): time over which decay emissions are measured
        """
        self.isotope = isotope
        self.exposure = exposure
        self.cooldown = cooldown
        self.integration = integration
        name = kwargs.get('name',isotope.name)
        super().__init__(name=name,**kwargs)    
    
    @property
    def rate(self):
        """Get the average decay rate over the integation interval"""
        tau = self.isotope.halflife / log(2)
        if self.integration <= 0:
            self.integration = tau / 100
        R0 = self.isotope.activationrate * (1-exp(-self.exposure/tau))
        a = self.cooldown
        b = a + self.integration
        return R0 * (exp(-a/tau) - exp(-b/tau)) * tau/(self.integration)
   
    def getfullspec(self):
        return "exposure=%s, cooldown=%s, integration=%s" %\
        (self.exposure, self.cooldown, self.integration)

    def __repr__(self):
        return "CosmogenicActivation(%s, %s)"%(self.name, self.getfullspec())
    

#todo: define a combined cosmogenic exposure spec controls expoure, cooldown, integration
#       for all contained classes
class MultiCosmogenic(CombinedSpec):
    """Multiple cosmogenically-activated isotopes that share exposure times"""
    def __init__(self,isotopes,exposure, cooldown=0, integration=0,
                 name="Cosmogenic Activation",**kwargs):
        specs = [ CosmogenicActivation(iso) for iso in isotopes ]
        super().__init__(name=name,specs=specs,**kwargs)
        self.min_halflife = min([iso.halflife for iso in isotopes])
        self._cooldown = cooldown
        self._exposure = exposure
        self._integration = integration
        
        
    @property
    def exposure(self):
        return self._exposure
    @exposure.setter
    def exposure(self, newexp):
        self._exposure = newexp
        for spec in self._specs:
            spec.exposure = self._exposure
    
    @property
    def cooldown(self):
        return self._cooldown
    @cooldown.setter
    def cooldown(self, newcool):
        self._cooldown = newcool
        if self._cooldown <= 0:
            self._cooldown = 0
        for spec in self._specs:
            spec.cooldown = self._cooldown
    
    @property
    def integration(self):
        return self._integration
    @integration.setter
    def integration(self, newint):
        self._integration = newint
        if self._integration <= 0:
            self._integration = self.min_halflife/100
        for spec in self._specs:
            spec.integration = self._integration
    
    def getfullspec(self):
        return "exposure=%s, cooldown=%s, integration=%s" %\
        (self.exposure, self.cooldown, self.integration)
        
    def __repr__(self):
        return "CosmogenicActivation(%s)"%(self.getfullspec())
            
        
