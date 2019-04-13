import abc
import operator
import numpy as np
from uncertainties import ufloat
from uncertainties.unumpy import uarray
import logging
log = logging.getLogger(__name__)
from .. import units
from .histogram import Histogram

class SimDocEval(abc.ABC):
    """Extract a reducible value from a document database (targeted at a 
    MongoSimsDB). 

    ----------------------------------------------------
    Concrete classes MUST override the following methods:
    ----------------------------------------------------
    
    parse(self, doc, match): Extract the requested value from the raw dictionary
        object returned from the DB, and apply any necessary unit conversions
        This could also be a hook to get the value from a file on disk
        The value should have correct units and ideally have uncertainties
        (i.e. be a python `uncertainties.Variable` object) 
    
    ----------------------------------------------------
    Concrete classes SHOULD override the following methods:
    ----------------------------------------------------
    _key(self):  Generate a unique string key for the requested value that can 
        be used for caching. Suggested form is `Classname(arg1, arg2, ...)`

    project(self, projection): Modify the projection operator for a mongodb
        query. By default the projection will include the entire document, so 
        specifying only the keys necessary will reduce the IO.  In order to 
        avoid colbbering other projection results, only "<key>:True" type 
        operators should be added.  Projection could be modified in-place and 
        also returned

    ----------------------------------------------------
    Other useful methods to override:
    ----------------------------------------------------
    norm(self, result, match): Normalize the result to the original SimDataMatch
        IF not implemented, this just returns result

    reduce(self, result1, result2): reduce two prior results into a single 
        value. Default implementation is to add

    """
    ####### Overridable methods   ##############
    @abc.abstractmethod
    def parse(self, doc, match):
        pass

    def project(self, projection):
        return projection
    
    def norm(self, result, match):
        if self.livetimenormed:
            try:
                return result / match.livetime
            except ZeroDivisionError:
                log.warnking("SimDataMatch found with 0 livetime %s %s",
                             match.id, match.query)
                return result / (1e-6*units.second)
        return result

    def reduce(self, result1, result2):
        return result1 + result2
    
    #should we cache this??
    def _key(self):
        return "%s(%s)"%(type(self).__name__,
                         ",".join("%s=%s"%(key,val) 
                                  for key,val in self.__dict__.items()))
    
    ######## Private methods ###################
        
    @property
    def key(self):
        return self._key()

    def __eq__(self, other):
        try:
            return self.key == other.key
        except AttributeError:
            return False

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        return self._key()

    def __repr__(self):
        return self._key()

    def __init__(self, label=None, livetimenormed=True,
                 *args, **kwargs): #should label be required?
        super().__init__(*args, **kwargs)
        self.label = label
        self.livetimenormed = livetimenormed

    @property
    def label(self):
        return self._label or self.key
    @label.setter
    def label(self, label):
        self._label = label





#some concrete evaluations
def splitsubkeys(document, key):
    if not key:
        return None
    for subkey in key.split('.'):
        document = document[subkey] #throw key error if not there
    return document

class UnitsHelper(object):
    def __init__(self, unit=None, unitkey=None, evalunitkey=splitsubkeys,
                 *args, **kwargs):
        """Apply a unit to an evaluated value. 
        Args:
            units: fixed units to apply or None. Can be a string in which case
                it will be parsed with the `self.units` object (`pint`)
            unitkey: key in the document where units are found. Will be added
                to the projection only if it already has values set. Will also
                be used to evaluate the units if evalunitkey is None
        
            evalunitkey: function to extract units from the returned document. 
                Takes 2 parameters: document and original key.  If not provided,
                the key is taken to be literal, with `.` (periods) replaced 
                with subscript operators.  Therefore this function will not work
                if any key actually contains a period. 

        """
        super().__init__(*args, **kwargs)
        self.unit = unit
        if isinstance(unit,str):
            self.unit = self.units(unit)
        self.unitkey = unitkey
        self.evalunitkey = evalunitkey 
    
    units = units
        
    def projectunit(self, projection):
        if self.unitkey and projection:
            projection[self.unitkey] = True
        return projection #shouldn't be necessary
    
    def applyunit(self, result, document):
        unit = self.unit
        if self.unitkey:
            try:
                unit = self.evalunitkey(document, self.unitkey) 
            except KeyError:
                pass
            if isinstance(unit,str):
                unit = self.units(unit)
        if unit:
            try:
                result = result * unit
            except ValueError: #result cannot be converted to unit
                pass
        return result
   
class DirectValue(SimDocEval, UnitsHelper):
    """Get a unit directly from a key. Converter is a function
    to convert the (usually string) result into a number. 
    errcalc is a function to calculate the error from the value
    _before_ units are applied. Defaults to sqrt(val) which only works if
    val is unitless
    """
    def __init__(self, val, converter=lambda x:x, errcalc=(np.sqrt),
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.val = val
        self.converter = converter
        self.errcalc = errcalc

    def project(self, projection):
        projection[self.val] = True
        return self.projectunit(projection)
    
    def parse(self, document, match):
        #should we just throw an exception if the key is bad?
        result = self.converter(splitsubkeys(document, self.val))
        err = self.errcalc(result)
        return self.applyunit(ufloat(result, err), document)
    
    def _key(self):
        return("DirectValue(%s,%s,%s)"%(self.val, 
                                     self.unit,
                                     self.unitkey))
    
class DirectSpectrum(SimDocEval):
    def __init__(self, speckey, specunit=None, specunitkey=None,
                 bin_edges=None,
                 binskey=None, binsunit=None, binsunitkey=None,
                 errcalc=None, scale=1,
                 *args, **kwargs):
        """Extract a list from `speckey` in the document and convert it to a 
        numpy array.  If `binskey` is provided, bin edges are read from
        that key. bin_edges can be used to directly provide bins instead or as 
        a default if binskey is not found. A ValueError is raised if 
        len(hist)+1 != len(bin_edges)

        Returns a Histogram object. If the histogram is unitless or has units
        of 1/binsunit, errors are calculated assuming poisson quantitities. For
        other error definitions, the user can supply the `errcalc` function
        which takes the fully-formed Histogram with units applied as argument
        and returns the array of errors

        Args:
          speckey (str): key in the document containing the list of bin values
          specunit: string or pint unit with the units that should be applied
              to the values list before any other operations
          specunitkey (str): key in the document containing the specunit. If 
              both `specunitkey` and `specunit` are provided, `specunit` acts 
              as a default if `specunitkey` isn't in the document
          bin_edges (list): list of bin edges corresponding to values. Should
              have length len(doc.speckey)+1
          binskey (str): key in document containing the list of bin edges
          binsunit: str or pint unit for the bin dimensions
          binsunitkey (str): key in document containing binsunit
          errcalc (func): custom error calculation function, in case units
              are already applied or sqrt(N) is not appropriate
          scale (float): scale the histogram after applying units
        """
        #TODO: add option to integrate/average over range
        super().__init__(*args, **kwargs)
        self.speckey = speckey
        self.specunit = UnitsHelper(specunit, specunitkey)
        self.bin_edges = bin_edges
        self.binskey = binskey
        self.binsunit = UnitsHelper(binsunit, binsunitkey)
        self.errcalc = errcalc
        self.scale = scale

    def project(self, projection):
        projection[self.speckey] = True
        self.specunit.projectunit(projection)
        if self.binskey:
            projection[self.binskey] = True
            self.binsunit.projectunit(projection)
        return projection

    def parse(self, document, match):
        #should we check that the key returns a list?
        hist = splitsubkeys(document, self.speckey)
        if isinstance(hist,(list, tuple)):
            hist = np.array(hist)
        bin_edges = self.bin_edges
        if self.binskey:
            try:
                bin_edges = np.array(splitsubkeys(document, self.binskey))
            except KeyError:
                pass
        
        try:
            bin_edges = self.binsunit.applyunit(bin_edges, document)
            hist = self.specunit.applyunit(hist, document)
        except AttributeError: #thrown if hist is not unit-able
            pass
            
        result = Histogram(hist, bin_edges)

        try:
            err = None
            if self.errcalc:
                err = self.errcalc(result)
            elif not hasattr(hist, 'units'):
                err = np.sqrt(hist)
            elif hist.dimensionless:
                err = np.sqrt(hist)
            elif (bin_edges and hasattr(bin_edges,'units') 
                  and hist.u == 1/bin_edges.u):
                err = np.sqrt(hist) / np.sqrt(bin_edges[1:]-bin_edges[:-1]) 
        except (AttributeError, TypeError): #numpy.sqrt is failing
            pass
            
        
        if err is not None:
            if hasattr(hist, 'units'):
                result = Histogram(uarray(hist.m,err.m)*hist.u, bin_edges)
            else:
                result = Histogram(uarray(hist, err), bin_edges)
        if(self.scale and self.scale != 1):
            result *= self.scale
        return result

    def _key(self):
        #do we need all the unit keys too? 
        return "DirectSpectrum({},{})".format(self.speckey, self.binskey)
        

class SpectrumAverage(DirectSpectrum):
    """Average the spectrum over the provided range"""
    def __init__(self, speckey, a=None, b=None, binwidths=True, **kwargs):
        super().__init__(speckey, **kwargs)
        self.a = a
        self.b = b
        self.binwidths = binwidths

    def parse(self, doc, match):
        return super().parse(doc, match).average(self.a, self.b, self.binwidths)
        
class SpectrumIntegral(DirectSpectrum):
    """Integrate the spectrum over the provided range"""
    def __init__(self, speckey, a=None, b=None, binwidths=True, **kwargs):
        super().__init__(speckey, **kwargs)
        self.a = a
        self.b = b
        self.binwidths = binwidths

    def parse(self, doc, match):
        return super().parse(doc, match).integrate(self.a,self.b,self.binwidths)
        
