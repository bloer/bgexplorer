import abc
import operator
import numpy as np

from .. import units
from .histogram import Histogram

class SimDocEval(abc.ABC):
    """Extract a reducible value from a document database (targeted at a 
    MongoSimsDB). 

    ----------------------------------------------------
    Concrete classes MUST override the following methods:
    ----------------------------------------------------
    
    parse(self, doc, match): Extract the requested value from the raw dictionary
        object returned fro mthe DB, and apply any necessary unit conversions
        This could also be a hook to get the value from a file on disk
    
    ----------------------------------------------------
    Concrete classes SHOULD override the following methods:
    ----------------------------------------------------
    __key(self):  Generate a unique string key for the requested value that can 
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
        return result

    def reduce(self, result1, result2):
        return result1 + result2;
    
    #should we cache this??
    def __key(self):
        return "%s(%s)"%(type(self).__name__,
                         ",".join("%s=%s"%(key,val) 
                                  for key,val in self.__dict__.items()))
    
    ######## Private methods ###################
        
    @property
    def key(self):
        return self.__key()

    def __eq__(self, other):
        try:
            return self.key == other.key
        except AttributeError:
            return False

    def __hash__(self):
        return hash(key)

    def __str__(self):
        return self.key

    def __repr__(self):
        return self.key

    def __init__(self, label=None): #should label be required?
        super().__init__()
        self.label = label

    @property
    def label(self):
        return self._label or self.key
    @label.setter
    def label(self, label):
        self._label = label





#some concrete evaluations
def splitsubkeys(document, key):
    for subkey in unitkey.split('.'):
        document = document[subkey] #throw key error if not there
    return document

class UnitsHelper(object):
    def __init__(self, unit=None, unitkey=None, evalunitkey=splitsubkeys):
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
        super().__init__()
        self.unit = unit
        if unit is not None:
            self.unit = self.units(unit)
        self.unitkey = unitkey
        self.evalunitkey = evalunitkey 
    
    units = units
        
    def projectunit(self, projection):
        if self.unitkey and projection:
            projection[unitkey] = True
        return projection #shouldn't be necessary
    
    def applyunit(self, result, document):
        unit = self.unit
        if self.unitkey:
            try:
                unit = self.evalunitkey(document, self.unitkey) 
            except KeyError:
                pass
            unit = self.units(unit)
        if unit:
            result *= unit
        return result
   
class DirectValue(SimDocEval, UnitsHelper):
    """Get a unit directly from a key. Converter is a function
    to convert the (usually string) result into a number
    """
    def __init__(self, val, converter=lambda x:x, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.val = val
        self.converter = converter

    def project(self, projection):
        projection[self.val] = True
        return self.projectunit(projection)
    
    def parse(self, document, match):
        #should we just throw an exception if the key is bad?
        result = converter(splitsubkeys(document, self.val))
        return self.applyunit(result, document)
    
    def __key(self):
        return("DirectValue(%s,%s,%s)"%(self.val, 
                                     self.unit,
                                     self.unitkey))
    

class DirectSpectrum(SimDocEval):
    def __init__(self, speckey, specunit=None, specunitkey=None,
                 bin_edges=None,
                 binskey=None, binsunit=None, binsunitkey=None,
                 *args, **kwargs):
        """Extract a list from `speckey` in the document and convert it to a 
        numpy array.  If `binskey` is provided, bin edges are read from
        that key. bin_edges can be used to directly provide bins instead or as 
        a default if binskey is not found. A ValueError is raised if 
        len(hist)+1 != len(bin_edges)

        Returns a 2-tuple of (hist, bin_edges) as numpy.histogram. 
        """
        #TODO: add option to integrate/average over range

        self.speckey = speckey
        self.specunit = UnitsHelper(specunit, specunitkey)
        self.bin_edges = bin_edges
        self.binskey = binskey
        self.binsunit = UnitsHelper(binsunit, binsunitkey)

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
        if isinstance(val,(list, tuple)):
            hist = np.array(val)
        bin_edges = self.bin_edges
        try:
            bin_edges = np.array(splitsubkeys(document, self.binskey))
        except KeyError:
            pass
        
        return Histogram(self.specunit.applyunit(hist, document),
                         self.binsunit.applyunit(bin_edges, document))

    def __key(self):
        #do we need all the unit keys too? 
        return "DirectSpectrum({},{})".format(self.speckey, self.binskey)
        


class LivetimeNormed(SimDocEval):
    """Normalize the evaluated result by livetime"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def norm(self, result, match):
        result /= match.livetime
        return result



class LivetimeNormedValue(DirectValue, LivetimeNormed):
    """Get a value by key and normalize by livetime"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class LivetimeNormedSpectrum(DirectSpectrum, LivetimeNormed):
    """Get a spectrum and normalize by livetime"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
        
 
