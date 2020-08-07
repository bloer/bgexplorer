import copy

class SimsDbView(object):
    """ This class's members specify how to load and interpret simulation
    database entries and how to view results from models
    """
    defaultgroups = {
        "Component": lambda match: [c.name for c in match.assemblyPath],
        "Material": lambda match: match.component.material,
        #"Source": lambda match: match.spec.name,
        #"Source Category": lambda match: match.spec.category,
        "Source": lambda match: [match.spec.category, match.spec.name],
    }
    defaultjoinkey = '___'

    def __init__(self, simsdb=None, summarypro=None, summarycolumns=None,
                 groups=None, groupsort=None, groupjoinkey=None,
                 values=None, values_units=None,
                 spectra=None, spectra_units=None, values_spectra=None):
        """ Constructor
        Args:
            simsdb (SimulationsDB): A SimulationsDB concrete instance
            summarypro: object specifying projection for simdb summary tables
            summarycolumns (list): list of columns for simdb summary tables
                                   (optional, will use all keys if empty)
            groups (dict): dict of grouping functions to cache on all hits
            groupsort (dict): dictionary of lists to sort group values
            groupjoinkey (str): string to join nested lists of groups
            values (dict): dictionary of value functions to cache on all hits
            values_units (dict): optional dictionary of units to render values
                                 in in the cached datatable
            spectra (dict): Functions to generate spectra for all simdatamatches
            spectra_units (dict): render spectra in the specified units
            values_spectra (dict): if an entry in `values` is associated to an
                                   entry in `spectra`, generate a link

        Note that all of the 'spectra' keys are currently not used

        """
        self.simsdb = simsdb
        self.summarypro = summarypro
        self.summarycolumns = summarycolumns
        self.groups = groups or self.defaultgroups
        self.groupsort = groupsort or {}
        self.groupjoinkey = groupjoinkey or self.defaultjoinkey
        self.values = values or {}
        self.values_units = values_units or {}
        self.spectra = spectra or {}
        self.spectra_units = spectra_units or {}
        self.values_spectra = values_spectra or {}

        #replace groupsort nested lists with joined strings
        for key,val in list(self.groupsort.items()):
            if isinstance(val,(list, tuple)):
                val = [self.groupjoinkey.join(i) if isinstance(i,(list,tuple))
                                                 else i
                       for i in val]
                self.groupsort[key] = val

    def clone(self, newdb):
        """ Clone this view with a new db object"""
        clone = copy.copy(self)
        clone.simsdb = newdb
        return clone

    def __repr__(self):
        return f"SimsDbView({self.simsdb})"

    def __str__(self):
        return self.__repr__()
