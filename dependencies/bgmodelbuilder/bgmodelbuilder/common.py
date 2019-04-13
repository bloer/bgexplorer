"""
Common functions and utility classes shared by other units
"""
import inspect
from copy import copy
import pint
import uncertainties

###### physical units #######
units = pint.UnitRegistry()
units.auto_reduce_dimensions = False #this doesn't work right
units.errors = pint.errors
units.default_format = '~P'
#fix Bq, add ppb units
units.load_definitions([
    "Bq = Hz = Bq = Becquerel",
    "ppb_U = 12 * mBq/kg = ppbU",
    "ppb_Th = 4.1 * mBq/kg = ppbTh",
    "ppm_K = 31 * mBq/kg = ppbK",
    "ppb_K = 0.001 * ppm_K = ppbK",
    "ppt_U = 0.001 * ppb_U = pptU",
    "ppt_Th = 0.001 * ppb_Th = pptTh",
    "ppt_K = 0.001 * ppb_K = pptK",
    "dru = 1./(kg * keV * day) = DRU",
    "kky = kg * keV * year = kg_keV_yr",
])
    

#monkey-punch round() capability onto uncertainties, mostly needed for tests
uncertainties.core.Variable.__round__ = lambda self,n=0: round(self.n,n)
uncertainties.core.AffineScalarFunc.__round__ = lambda self,n=0: round(self.n,n)


def ensure_quantity(value, defunit=None, convert=False):
    """Make sure a variable is a pint.Quantity, and transform if unitless
    
    Args:
        value: The test value
        defunit (str,Unit, Quanty): default unit to interpret as
        convert (bool): if True, convert the value to the specified unit 
    Returns:
        Quantity: Value if already Quantity, else Quantity(value, defunit)
    """
    if value is None:
        return None
    try:
        qval = units.Quantity(value)
    except Exception: 
        #Quantity can't handle '+/-' that comes with uncertainties...
        valunit = value.rsplit(' ',1)
        q = valunit[0]
        u = valunit[1] if len(valunit)>1 else ''
        if q.endswith(')'):
            q = q[1:-1]
        qval = units.Measurement(uncertainties.ufloat_fromstr(q), u)
        
    #make sure the quantity has the same units as default value
    if (defunit is not None and 
        qval.dimensionality != units.Quantity(1*defunit).dimensionality):
        if qval.dimensionality == units.dimensionless.dimensionality:
            qval = units.Quantity(qval.m, defunit)
        else:
            raise units.errors.DimensionalityError(qval.u, defunit)
    
    return qval.to(defunit) if convert and defunit else qval
    


def to_primitive(val, renameunderscores=True, recursive=True,
                 replaceids=True, stringify=(units.Quantity,)):
    """Transform a class object into a primitive object for serialization"""
    
    #if replaceids and hasattr(val, 'id'):
    #    val =  val.id   #id can be a property, so only use _id
    if replaceids and hasattr(val, '_id'):
        val =  val._id

    elif inspect.getmodule(val): #I think this tests for non-builtin classes
        if hasattr(val, 'todict'): #has a custom conversion
            val =  val.todict()
        elif isinstance(val, stringify):
            val =  str(val)
        elif hasattr(val, '__dict__'): #this is probably going to break lots
            val =  copy(val.__dict__)
        else: #not sure what this is...
            raise TypeError("Can't convert %s to exportable",type(val))
            
    if recursive:
        if isinstance(val, dict):
            removeclasses(val, renameunderscores, recursive, replaceids, 
                          stringify)
        elif isinstance(val, (list,tuple)):
            val = type(val)(to_primitive(sub, renameunderscores, recursive, 
                                         replaceids, stringify) for sub in val)
    return val
    

####### Functions for dictionary export of complex structures #####
def removeclasses(adict, renameunderscores=True, recursive=True,
                  replaceids=True, stringify=(units.Quantity,)):
    """Transform all custom class objects in the dict to plain dicts
    Args:
        adict (dict): The dictionary to update in place
        renameunderscores (bool): For any key starting with a single underscore,
            replace with the regular. I.e. '_key'->'key'. Note '_id' will 
            NOT be replaced
        recursive (bool): call removeclasses on any dicts stored as objects
            inside this dictionary
        replaceids (bool): If true, replace any object with an 'id' attribute
            by that object's id
        stringify (list): list of classes that should be transformed into 
            string objects rather than dictionaries
    """

    underkeys = []
    
    for key, val in adict.items():
        #check if we need to rename this key
        if (key != '_id' and hasattr(key,'startswith') and 
            key.startswith('_') and not key.startswith('__')):
            underkeys.append(key)
        
        adict[key] = to_primitive(val, renameunderscores, recursive, 
                                  replaceids, stringify)
        
    if renameunderscores:
        for key in underkeys:
            adict[key[1:]] = adict[key]
            del adict[key]
    
    return adict
