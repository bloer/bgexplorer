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
from math import sqrt
import numbers
from uncertainties import ufloat

class EmissionSpec(Mappable):
    """ Define a specification to determine emissions from some component.
    
    Each component will define a list of specs mapping to one or more
    simulated conversion efficiencies. Each spec has a 'primary' control
    (e.g., hours exposure for cosmogenic activation) from which a
    'susceptibility' is defined when combined with the conversion eff.
    
    
    Sub-classes should override the get_rate and get_susceptibility methods.    
    """

    #have a finite list of allowed distribution types
    _default_distribution = "bulk"
        
    def __init__(self, name="", 
                 distribution=_default_distribution, normfunc=None,
                 islimit=False, 
                 category="", comment="", moreinfo=None,
                 appliedto=None,
                 querymod = None,
                 parent=None,
                 **kwargs):
        """Make a new EmissionSpec

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
            islimit (bool): Is this an upper limit from a measurement?
            category(str): A descriptive category for higher-order groupings. 
                for example, Cosmogenic Activation, Radon Daughter
            comment (str) A descriptive comment
            moreinfo (dict): key-value pairs for any other information
            appliedto (set): set of components this spec is bound to
            querymod (dict): overrides for database queries
            parent (EmissionSpec): set the owner in case this is a subspec
        """
        super().__init__(**kwargs)

        self.name = name
        self.distribution = distribution
        self.normfunc = normfunc
        self.islimit = islimit
        self.category = category or type(self).__name__
        self.comment = comment
        self.moreinfo = moreinfo or {}
        self.appliedto = appliedto or set()
        self.querymod = querymod or {}
        self.parent = parent
        
    def __str__(self):
        return "%s('%s')"%(type(self).__name__, self.name)
        
    def __repr__(self):
        return ("EmissionSpec('%s',distribution='%s',category='%')"
                %(self.name, self.distribution, self.category))
        
    def getcomment(self):
        """Get spec comment. Used to include additional info"""
        return self.comment
        
    #subclasses should override
    def getfullspec(self):
        return ''
        
    @property
    def rate(self):
        """Get the unnormalized emission rate from this source"""
        return 0
        
    @property
    def err(self):
        """Get the uncertainty in rate from this source as a fraction"""
        return 0

    @property
    def ratewitherr(self):
        """Get the rate with error"""
        rate = self.rate
        if rate is None:
            return None
        if self.err:
            rate = rate.plus_minus(self.err, relative=True)
        return rate

    def getratestr(self, sigfigs=None):
        if self.rate is None:
            return "undefined"
        try:
            res=""
            if self.islimit:
                res += "<"
            format = (".%dg"%sigfigs) if sigfigs else "g"
            if isinstance(self.rate, units.Quantity):
                format = ":~"+format+"P"
            else:
                format = ":"+format
            res += ("{"+format+"}").format(self.rate)
            if self.err:
                res += " +/- {:.2g}%".format(self.err*100.)
            return res
        except Exception as e:
            return "error: "+str(e)
    
    #concrete classes _should_ override this moethod
    def emissionrate(self,component):
        """Normalize the emission rate to the component"""
        multiplier = 0
        if self.normfunc:
            if callable(self.normfunc): #its a function
                multiplier = self.normfunc(component)
            elif self.normfunc.lower() in ("piece","perpiece","per piece",
                                           "per-piece","per_piece"):
                multiplier = 1
            elif type(self.normfunc) is str:
                #evaluate it. the __builtins__ thing somewhat protects 
                #against malicious stuff. 
                multiplier = eval(self.normfunc, 
                                  {'__builtins__':{},'units':units},
                                  {'component':component, 'piece':1})
            elif isinstance(self.normfunc, numbers.Number):
                multiplier = self.normfunc
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

        return (self.ratewitherr * multiplier).to('1/s')
    
    def totalemissionrate(self):
        """Get the total emission rate from all associated components 
        and their global weights
        """
        return sum(self.emissionrate(comp) * comp.gettotalweight() 
                   for comp in self.appliedto)

    def getstatus(self):
        result = ""
        #first make sure units are correct
        for comp in self.appliedto:
            try:
                self.emissionrate(comp).to('1/s')
            except units.errors.DimensionalityError:
                result += (" DimensionalityError: emissionrate for comp '{}' ({}) "
                           .format(comp.name, comp.id))
        return result
        
    def getrootspec(self):
        """Get the top-level EmissionSpec that we belong to"""
        try:
            return self.parent.getrootspec()
        except AttributeError:
            return self
    
    _copy_attrs = ['normfunc', 'distribution', 'category', 'appliedto']
    
    def todict(self):
        """Export this instance to a plain object"""
        result = copy(self.__dict__)
        result['__class__'] = type(self).__name__
        #remove attributes that are copied from parent
        if self.parent:
            for attr in self._copy_attrs:
                del result[attr]
        #all 'appliedto' and 'parent' will get rebuilt on restore
        result.pop('appliedto',None)
        result.pop('_appliedto', None)
        result.pop('parent', None)
        result = removeclasses(result, replaceids=False)
        return result

        

class CombinedSpec(EmissionSpec):
    """Utility class to group multiple specs into one"""
    def __init__(self,name="",subspecs=[],**kwargs):
        self._subspecs = []
        super().__init__(name=name, **kwargs)
        #override category if left to default
        if self.category == 'CombinedSpec':
            self.category = 'RadioactiveContam'
        self.subspecs = subspecs 
        
    @property
    def rate(self):
        return sum(spec.rate for spec in self._subspecs)
    
    @property
    def err(self):
        return (sum((spec.err*spec.rate)**2 for spec in self._subspecs)**0.5 
                / self.rate).m
    
    @property
    def islimit(self):
        #todo: this is probably not a useful definition
        return all(spec.islimit for spec in self._subspecs)
    
    @islimit.setter
    def islimit(self,val):
        pass

    def emissionrate(self,component):
        return sum(spec.emissionrate(component) for spec in self._subspecs)
        

    @property
    def subspecs(self):
        return self._subspecs

    @subspecs.setter
    def subspecs(self, newsubspecs=[]):
        self._subspecs = []
        for spec in newsubspecs:
            self.addspec(spec)
    
    
    def addspec(self,spec):
        if not isinstance(spec, EmissionSpec):
            spec = buildspecfromdict(spec)
        #todo: is this really a good plan??
        for attr in self._copy_attrs:
            setattr(spec,attr, getattr(self,attr))
        spec.parent = self
        self._subspecs.append(spec)
        
    def __repr__(self):
        return "CombinedSpec('%s', subspecs=%s)"%(self.name, self.subspecs)

    def updatesubspecs(self, attr, val):
        for sub in self.subspecs:
            setattr(sub, attr, val)
            
    def getstatus(self):
        return "".join(s.getstatus() for s in self.subspecs)
            
    #overload __getitem__ so we can unpack subspecs directly
    #should we allow deep unpacking???
    def __getitem__(self,key):
        return self.subspecs[key]

    @classmethod
    def copytosubs(cls, attr):
        """For the named attribute, copy it to our subspecs on assignment"""
        hidden = '_'+attr
        def get(self):
            return getattr(self, hidden)
        def set(self,val):
            self.updatesubspecs(attr, val)
            return setattr(self, hidden, val)
        setattr(cls, attr, property(get, set))

for attr in EmissionSpec._copy_attrs:
    CombinedSpec.copytosubs(attr)
        

class RadioactiveIsotope(Mappable):
    def __init__(self,halflife=1*units.second,name=None, **kwargs):
        super().__init__(**kwargs)
        self.halflife = ensure_quantity(halflife, units.seconds)
        self.name = name        

class RadioactiveContam(EmissionSpec):
    """ Spec for a (long-lived) radioactive isotope.
    
    The specification is defined by the isotope name, the distribution 
    (bulk, surface, surface_in or surface_out), and the decay rate in mBq/kg
    for bulk surfaces or mBq/cm2 for surface sources. 
    
    """

    def __init__(self, name='', rate='0 Bq/kg', err=0, isotope=None, **kwargs):
        self.rate = rate
        self.err = err
                        
        self.isotope = isotope or name
        if isinstance(self.isotope, dict): #handle imports
            self.isotope = RadioactiveIsotope(**self.isotope)
        if isinstance(self.isotope, RadioactiveIsotope):
            kwargs.setdefault('_id', isotope.id)
        if not name:
            if isinstance(self.isotope, RadioactiveIsotope):
                name = self.isotope.name
            elif self.isotope:
                name = self.isotope
        super().__init__(name=name, **kwargs)
        
    @property
    def rate(self):
        return self._rate
        
    @rate.setter
    def rate(self, newrate):
        self._rate = ensure_quantity(newrate)

    @property
    def err(self):
        return self._err

    @err.setter
    def err(self,newerr):
        self._err = newerr
        if(newerr != 0):
            if isinstance(newerr,str):
                newerr = newerr.replace("%","*0.01").replace("percent","*0.01")
            err = ensure_quantity(newerr)
            if not err.dimensionless: #convert to fractional error
                if err.dimensionality == self.rate.dimensionality:
                    self._err = (err.to(self.rate.u)/self.rate).m
                else:
                    msg = "err must be fractional or in same units as rate"
                    raise units.DimensionalityError(self.rate.u, err.u,
                                                    extra_msg=msg)
            else:
                self._err = err.m
                                                    
        
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
    _mode_types = ("free", "trapped")
    _tau_pb210 = 22.3*units.year / log(2)    
    _tau_rn222 = 3.8 * units.day / log(2)
    _default_column_height = 10*units.cm
    
    def __init__(self,radonlevel=100*units('Bq/m**3'), exposure=1*units.day,  
                 distribution='surface', 
                 column_height = _default_column_height, mode="free",
                 **kwargs):
        self.radonlevel = ensure_quantity(radonlevel,"Bq/m^3")
        self.exposure = ensure_quantity(exposure, units.day)
        self.column_height = ensure_quantity(column_height, units.cm)
        if mode not in self._mode_types:
            print("Uknown mode %s; using 'free'"%mode)
            mode="free"
        self.mode = mode
        kwargs.setdefault('isotope', 'Pb210')
        kwargs.setdefault('distribution','surface')
        super().__init__(**kwargs)
    
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
    
    @rate.setter
    def rate(self,val):
        pass
        
    def getfullspec(self):
        return "%s, %s, %s"%(self.radonlevel, self.exposure, self.distribution)
    
    def __repr__(self):
        return "RadonExposure(%s)"%(self.getfullspec())
                                                         



class DustAccumulation(CombinedSpec):
    """Dust deposited onto a surface or into the bulk of a material.
    Users specify the type and concentration of radioactive contaminants
    in the dust, how the dust distribution is modeled, and the accumulation
    rate, mass per surface area or total mass
    
    WARNING: This class doesn't actually work right now!

    Args:
        dustmass(Quantity): mass of dust, units should match distribution
            e.g. dimensionless for bulk, kg/cm2 for surface, or kg for per piece
        
    """        
    def __init__(self, dustmass=100*units('nanogram/cm**2'), 
                 **kwargs):
        kwargs.setdefault('distribution','surface')
        super().__init__(**kwargs)
        self.dustmass = ensure_quantity(dustmass)
        #todo: need to override subspecs emissionrate

    def getfullspec(self):
        return "dustmass=%s"%self.dustmass
        
    @property
    def dustmass(self):
        return self._dustmass
    
    @dustmass.setter
    def dustmass(self, newmass):
        self._dustmass = newmass
        #do something to subspecs here


class CosmogenicIsotope(RadioactiveIsotope):
    def __init__(self, halflife=1*units.second, 
                 activationrate=1*units('1/kg/day'), name=None,
                 **kwargs):
        self.activationrate = ensure_quantity(activationrate, "1/kg/day")
        super().__init__(halflife, name, **kwargs)
        
        
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
        kwargs.setdefault('name', isotope.name)
        super().__init__(isotope=isotope, **kwargs)    
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

    @rate.setter
    def rate(self, newrate):
        pass
   
    def getfullspec(self):
        #return "exposure=%s, cooldown=%s, integration=%s" %\
        #(self.exposure, self.cooldown, self.integration)
        #TODO: find a way to make standalone and subspec make sense
        return "halflife=%s, activationrate=%s" %\
            (self.isotope.halflife, self.isotope.activationrate)

    def __repr__(self):
        return "CosmogenicSource(%s, %s)"%(self.name, self.getfullspec())
    

class CosmogenicActivation(CombinedSpec):
    """Multiple cosmogenically-activated isotopes that share exposure times"""
    def __init__(self,isotopes=[],exposure=0, cooldown=0, integration=0,
                 **kwargs):
        #subspecs = [ CosmogenicSource(iso) for iso in isotopes ]
        super().__init__(**kwargs)
        self.min_halflife = 1*units.second
        self.cooldown = cooldown
        self.exposure = exposure
        self.integration = integration
        self.isotopes = isotopes
        

    _copy_attrs = (CombinedSpec._copy_attrs + 
                   ['exposure', 'cooldown', 'integration'])
    
    
    @property
    def isotopes(self):
        return self._isotopes
    @isotopes.setter
    def isotopes(self, newisos):
        self._isotopes = [CosmogenicIsotope(**iso) if isinstance(iso, dict) 
                          else iso for iso in newisos]
        self._subspecs = []
        for iso in self._isotopes:
            self.addspec(CosmogenicSource(iso))
        if self._isotopes:
            self.min_halflife = min([iso.halflife for iso in self._isotopes])
        else:
            self.min_halflife = 1*units.second

    @property
    def exposure(self):
        return self._exposure
    @exposure.setter
    def exposure(self, newexp):
        self._exposure = ensure_quantity(newexp, units.day)
        self.updatesubspecs('exposure', self._exposure)
    
    @property
    def cooldown(self):
        return self._cooldown
    @cooldown.setter
    def cooldown(self, newcool):
        self._cooldown = max(ensure_quantity(newcool, units.day), 0*units.day)
        self.updatesubspecs('cooldown', self._cooldown)
    
    @property
    def integration(self):
        return self._integration
    @integration.setter
    def integration(self, newint):
        self._integration = max(ensure_quantity(newint, units.year), 
                                self.min_halflife/100)
        self.updatesubspecs('integration', self._integration)
    
    def getfullspec(self):
        return "exposure=%s, cooldown=%s, integration=%s" %\
        (self.exposure, self.cooldown, self.integration)
        
    def __repr__(self):
        return "CosmogenicActivation(%s)"%(self.getfullspec())
            
    def todict(self):
        result = super().todict()
        del result['subspecs']
        #this gets calculated automatically
        del result['min_halflife']
        return result
        
def buildspecfromdict(args):
    """Construct a EmissionSpec from an exported dictionary"""
    #todo: this is pretty crude and will probably break...
    return eval(args.pop('__class__'))(**args)
    

