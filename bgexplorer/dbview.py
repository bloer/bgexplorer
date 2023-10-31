import copy
import gzip
import zipfile
import tarfile
import itertools

from bgmodelbuilder.simulationsdb.hiteffdb import HitEffDB
from bgmodelbuilder.simulationsdb.hiteff import HitEffDbConfig


class SimsDbView(object):
    """ This class's members specify how to load and interpret simulation
    database entries and how to view results from models
    """
    defaultgroups = {
        "Component": lambda match: [c.name for c in match.assemblyPath],
        "Material": lambda match: match.component.material,
        # "Source": lambda match: match.spec.name,
        # "Source Category": lambda match: match.spec.category,
        "Source": lambda match: [match.spec.category, match.spec.name],
    }
    defaultjoinkey = '___'

    def __init__(self, simsdb=None, summarypro=None, summarycolumns=None,
                 groups=None, groupsort=None, groupjoinkey=None,
                 values=None, values_units=None,
                 spectra=None, spectra_units=None, values_spectra=None,
                 upload_handler=None, description=''):
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
            upload_handler (func): function to handle new entry upload requests
            description (str): description to show on summary page

        Note that all of the 'spectra' keys are currently not used

        The `upload_handler` function should accept a list of file-like objects
        and and a SimulationsDB object and return a dict containing:
            entries: dict of {filename: primarykey} for all entries inserted/updated
            errors: dict of {filename: string}  error messages if any. Use
                    `None` for the filename of any generic errors

        one utility function `json_upload_handler` is provided

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
        self.upload_handler = upload_handler
        self.description = description

        # replace groupsort nested lists with joined strings
        for key, val in list(self.groupsort.items()):
            if isinstance(val, (list, tuple)):
                val = [self.groupjoinkey.join(i) if isinstance(i, (list, tuple))
                       else i
                       for i in val]
                self.groupsort[key] = val

    def handle_uploads(self, files):
        """ Handle file uploads """
        if self.upload_handler is None:
            raise NotImplementedError("No upload handler defined")
        return self.upload_handler(files, self.simsdb)

    def clone(self, newdb):
        """ Clone this view with a new db object"""
        clone = copy.copy(self)
        clone.simsdb = newdb
        return clone

    def __repr__(self):
        return f"SimsDbView({self.simsdb})"

    def __str__(self):
        return self.__repr__()

    def flatten_gval(self, gval):
        """ Group evaluation functions can produce a list or tuple. This
        function converts to a string by joining each value with the join key
        Args:
            gval: the output of a grouping function
        """
        if isinstance(gval, (list, tuple)):
            gval = self.groupjoinkey.join(str(v) for v in gval)
        return gval

    def unflatten_gval(self, gval, force=False):
        """ convert a flattened value back to a list
        Args:
            gval (str): a flattened group
            force (bool): if True, always convert to a single-length list
        Returns:
            list: if `gval` can be split or `force` is True, otherwise
                  return `gval`
        """
        if not isinstance(gval, (str, bytes)):
            return gval
        if force or (self.groupjoinkey in gval):
            gval = gval.split(self.groupjoinkey)
        return gval

    def evalgroup(self, match, groupname, flatten=True):
        """ Evaluate the group `groupname` for the given match
        Args:
            match (SimDataMatch): The sim request to evaluate
            groupname (str): name of group in `self.groups` to evaluate
            flatten (bool): if True (default) call `flatten_gval`
        Returns:
            the result of the group function on match`
        """
        gval = self.groups[groupname](match)
        if flatten:
            gval = self.flatten_gval(gval)
        return gval

    def evalgroups(self, match, flatten=True):
        """ Evaluate all group functions for `match`
        Args:
            match (SimDataMatch): request to evaluate
            flatten (bool): If True (default), call `flatten_gval`
        Returns:
            dict: of groupname: evaluated function
        """
        return {key: self.evalgroup(match, key, flatten) for key in self.groups}

    def is_subgroup(self, g1, g2):
        """ Test whether g1 is a subgroup of g2 (or equal) """
        g1 = self.unflatten_gval(g1, force=True)
        g2 = self.unflatten_gval(g2, force=True)
        try:
            return len(g1) >= len(g2) and all(a == b for a, b in zip(g1, g2))
        except TypeError:
            # somethign returned None
            return False


class HitEffDbView(SimsDbView):
    """ Temporary hack to construct a simsdbview from a HitEffDB """
    def __init__(self, hiteffdb, **kwargs):
        dbconfig = hiteffdb.dbconfig
        if not dbconfig.display_values:
            dbconfig.update_from_collection()
        summarypro = {k: 1 for k in dbconfig.display_columns}
        summarypro['id'] = '$_id'
        super().__init__(simsdb=hiteffdb,
                         summarypro=summarypro,
                         summarycolumns=dbconfig.display_columns,
                         upload_handler=json_upload_handler,
                         **kwargs)

    @property
    def values(self):
        return self.simsdb.dbconfig.display_values

    @values.setter
    def values(self, newval):
        pass

    @property
    def spectra(self):
        return self.simsdb.dbconfig.display_spectra

    @spectra.setter
    def spectra(self, val):
        pass

    @property
    def values_units(self):
        return {k: v.display_unit for k, v in self.values.items()}

    @values_units.setter
    def values_units(self, newval):
        pass

    @property
    def spectra_units(self):
        return {k: v.display_unit for k, v in self.spectra.items()}

    @spectra_units.setter
    def spectra_units(self, newval):
        pass

    @property
    def values_spectra(self):
        return {k: v.link_spectrum for k, v in self.values.items() if v.link_spectrum}

    @values_spectra.setter
    def values_spectra(self, newval):
        pass




# utilities to handle file uploads:

def json_upload_handler(files, simsdb):
    """ This is a utility function to simplify inserting a list of JSON files
    into a SimulationsDB. Each file should be either a JSON file or zip
    or tar archive, and the JSON or tar may additionally be gzipped.
    This fulfills the requirements of a SimDataView update_handler argument

    Args:
        files (list): list of file-like objects
        simsdb (SimulationsDB): DB wrapper to insert into
    Returns:
        dict: with keys `errors` and `entries`
    """
    result = dict(entries={}, errors={})
    extracted = map(iterate_archive, files)
    for i, jfile in enumerate(itertools.chain.from_iterable(extracted)):
        # first make sure we can handle this type of file
        filename = getattr(jfile, 'filename', f'_file{i}')
        decomp = transparent_gzip(jfile)
        try:
            newentry = simsdb.addentry(decomp.read(), fmt="json")
            result['entries'][filename] = newentry
        except BaseException as e:
            result['errors'][filename] = "Error inserting entry: %s" % e
    return result


def iterate_archive(afile):
    """ If `afile` is a zip or tar archive (gzipped or not), return a list
    of the files stored inside.

    Otherwise return [afile], i.e.; the file wrapped in a list
    """
    files = [afile]
    try:
        tf = tarfile.open(fileobj=afile)
        files = [tf.extractfile(name) for name in tf.getnames()]
        for f, name in zip(files, tf.getnames()):
            f.filename = name
    except tarfile.TarError:
        afile.seek(0)
        pass
    try:
        zf = zipfile.ZipFile(afile)
        files = [_ZipExtSeekable(zf, name) for name in zf.namelist()]
    except zipfile.BadZipFile:
        afile.seek(0)
        pass

    return files


def transparent_gzip(afile):
    """ If `afile` is gzipped, return a `gzip.GzipFile`, otherwise return `afile
    Args:
        afile: a bytes-like object
    Returns:
        the decompressed bytes-like object
    """
    if afile.read(2) == b'\x1f\x8b':
        afile.seek(0)
        return gzip.GzipFile(fileobj=afile, mode='r')
    else:
        afile.seek(0)
        return afile


class _ZipExtSeekable(object):
    """ Wrap a 3.6 ZipExtFile to emulate seek(0) """

    def __init__(self, zipfile, name):
        self.zipfile = zipfile
        self.filename = name
        self.seek(0)

    def seek(self, to, whence=None):
        # only seek(0) is sensible
        self.ext = self.zipfile.open(self.filename)

    def seekable(self):
        return True

    def __getattr__(self, attr):
        return getattr(self.ext, attr)
