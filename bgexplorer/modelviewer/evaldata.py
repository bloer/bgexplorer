# python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from itertools import chain
import datetime
import gzip
import copy
import multiprocessing
import time
import numpy as np
from uncertainties import unumpy
from io import BytesIO
from flask import abort
import pymongo
try:
    import matplotlib
    import matplotlib.figure
    import matplotlib.pyplot
except ImportError:
    matplotlib = None

from .. import utils
from bgmodelbuilder import units
from bgmodelbuilder.simulationsdb.histogram import Histogram
from bgmodelbuilder.common import try_reduce

import logging
log = logging.getLogger(__name__)


class ModelEvaluator(object):
    """ Utiilty class to generate data tables and spectra for non-temp models """

    def __init__(self, model, modeldb=None, simsdbview=None, genimages=True,
                 bypasscache=False, writecache=True):
        """ Constructor
        Args:
            model (BgModel): model object to evaluate
            modeldb (ModelDB): database cache collection
            simsdbview (SimsDbView): defines vals and spectra
            simsdbview (SimsDbView): defines vals and spectra
            bypasscache: (bool)
        """
        self.model = model
        self.cache = None
        if not modeldb:
            modeldb = utils.get_modeldb()
        if modeldb and not modeldb.is_model_temp(model.id):
            self.cache = modeldb.getevalcache()

        self.genimages = genimages
        self.bypasscache = bypasscache
        self.writecache = writecache
        self.simsdbview = simsdbview
        if simsdbview is None:
            self.simsdbview = utils.get_simsdbview(model=model)
        self.simsdb = self.simsdbview.simsdb

    def evalmodel(self, fillallcache=False):
        cached = self.readfromcache()
        if cached:
            return cached
        start = time.monotonic()
        log.debug(f"Starting evaluation of model {self.model.id}")

        # write the datatable header

        def _valhead(val):
            suffix = ''
            if val in self.simsdbview.values_units:
                suffix = f' [{self.simsdbview.values_units[val]}]'
            return f'V_{val}{suffix}'
        header = '\t'.join(chain(['ID'],
                                 (f'G_{g}' for g in self.simsdbview.groups),
                                 (_valhead(v) for v in self.simsdbview.values.keys())
                                 ))
        # now evaluate all matches
        data = self.evalmatches(self.model.simdata.values(), include_datatable=True)

        # Complete the result object
        datatable = '\n'.join((header, data['datatable'], ''))
        data['datatable'] = gzip.compress(datatable.encode())

        if self.cache is not None and fillallcache:
            for comp in self.model.getcomponents():
                self.evalcomponent(comp)
            for spec in self.model.getspecs(rootonly=True):
                self.evalspec(spec)

        self.finalize(data)
        log.debug("Finished evaluation of data for model %s in %s seconds",
                  self.model.id, time.monotonic()-start)
        return data

    def evalmatch(self, match):
        cached = self.readfromcache(match=match)
        if cached:
            return cached

        to_evaluate = list(chain(self.simsdbview.values.values(),
                                 self.simsdbview.spectra.values()))
        evals = self.simsdb.evaluate(to_evaluate, match)
        nvals = len(self.simsdbview.values)
        values = dict(zip(self.simsdbview.values.keys(), evals[:nvals]))
        spectra = dict(zip(self.simsdbview.spectra.keys(), evals[nvals:]))

        # convert spectra to requested units
        for specname, spectrum in spectra.items():
            unit = self.simsdbview.spectra_units.get(specname, None)
            if unit is not None:
                try:
                    spectrum.hist.ito(unit)
                except AttributeError:  # not a quantity
                    pass

        def _valtostr(key, val):
            # convert to unit if provided
            unit = self.simsdbview.values_units.get(key, None)
            if unit:
                try:
                    val = val.to(unit).m
                except AttributeError:  # not a Quantity...
                    pass
                except units.errors.DimensionalityError as e:
                    if val != 0:
                        log.warning(e)
                    val = getattr(val, 'm', 0)
            # convert to string
            val = "{:.3g}".format(val)
            if match.spec.islimit:
                val = '<'+val
            return val
        datatable = '\t'.join(chain([match.id],
                                    self.simsdbview.evalgroups(match).values(),
                                    (_valtostr(k, v) for k, v in values.items())))

        data = dict(values=values, spectra=spectra, datatable=datatable)
        self.finalize(data, match=match)
        return data

    def evalmatches(self, matches, include_datatable=False):
        data = None
        for match in matches:
            result = self.evalmatch(match)
            data = self._add_data(result, data, include_datatable)
        return data

    def evalcomponent(self, component):
        cached = self.readfromcache(component=component)
        if cached:
            return cached
        data = self.evalmatches(self.model.getsimdata(rootcomponent=component))
        self.finalize(data, component=component)
        return data

    def evalspec(self, spec):
        cached = self.readfromcache(spec=spec)
        if cached:
            return cached
        data = self.evalmatches(self.model.getsimdata(rootspec=spec))
        self.finalize(data, spec=spec)
        return data

    def _add_data(self, data1, data2=None, include_datatable=False):
        if not data2:
            result = data1
            if not include_datatable:
                result.pop('datatable', None)
        else:
            ss = self.simsdbview.spectra
            spectra = dict((k, try_reduce(ss[k].reduce,
                                          data1['spectra'].get(k, 0),
                                          data2['spectra'].get(k, 0)))
                           for k in ss)
            vv = self.simsdbview.values
            values = dict((k, try_reduce(vv[k].reduce,
                                         data1['values'].get(k, 0),
                                         data2['values'].get(k, 0)))
                          for k in vv)

            result = dict(spectra=spectra, values=values)
            if include_datatable:
                datatable = '\n'.join((data1.get('datatable', ''),
                                       data2.get('datatable', '')))
                result['datatable'] = datatable
        return result

    def finalize(self, data, component=None, spec=None, match=None, cache=True):
        if not data:
            return data
        data['modelid'] = self.model.id
        title = ''
        if component is not None:
            data['componentid'] = component.id
            title = f"Component={component.name}"
        if spec is not None:
            data['specid'] = spec.id
            title = f"Source={spec.name}"
        if match is not None:
            data['matchid'] = match.id
        if self.genimages:
            self.make_all_images(data, title)
        if cache:
            self.writetocache(data)
        return data

    def make_all_images(self, data, titlesuffix=''):
        data['spectrum_images'] = {k: self.spectrum_image(k, v, titlesuffix)
                                   for k, v in data['spectra'].items()}
        return data

    def spectrum_image(self, specname, spectrum, titlesuffix="",
                       logx=True, logy=True):
        if not hasattr(spectrum, 'hist') or not hasattr(spectrum, 'bin_edges'):
            # this is not a Histogram, don't know what to do with it
            return None
        unit = self.simsdbview.spectra_units.get(specname, None)
        if unit is not None:
            try:
                spectrum.hist.ito(unit)
            except AttributeError:  # not a quantity
                pass

        if matplotlib is None:
            abort(500, "Matplotlib is not available")
        #log.debug("Generating spectrum image")
        # apparently this aborts sometimes?
        try:
            x = spectrum.bin_edges.m
        except AttributeError:
            x = spectrum.bin_edges
        fig = matplotlib.figure.Figure()
        ax = fig.subplots()
        ax.errorbar(x=x[:-1],
                    y=unumpy.nominal_values(spectrum.hist),
                    yerr=unumpy.std_devs(spectrum.hist),
                    drawstyle='steps-post',
                    elinewidth=0.6,
                    )
        ax.set_title(' '.join((specname, titlesuffix)))
        if logx:
            ax.set_xscale('log')
        if logy:
            ax.set_yscale('log')
        if hasattr(spectrum.bin_edges, 'units'):
            ax.set_xlabel(f'Bin [{spectrum.bin_edges.units}]')
        if hasattr(spectrum.hist, 'units'):
            ax.set_ylabel(f"Value [{spectrum.hist.units}]")

        """
        # limit to at most N decades...
        maxrange = 100000
        ymin, ymax = plt.ylim()
        ymax = 10**ceil(log10(ymax))
        ymin = max(ymin, ymax/maxrange)
        plt.ylim(ymin, ymax)
        plt.tick_params(which='major',length=6, width=1)
        plt.tick_params(which='minor',length=4,width=1)
        iplt.gcf().set_size_inches(9,6)
        plt.gca().set_position((0.08,0.1,0.7,0.8))
        """
        out = BytesIO()
        fig.savefig(out, format='png')
        matplotlib.pyplot.close(fig)
        #log.debug("Done generating image")
        return out.getvalue()

    @staticmethod
    def pack_quantity(q):
        val = q
        err = 0
        unit = None
        try:
            val = q.m
            unit = '{:~P}'.format(q.u)
        except AttributeError:
            pass

        try:
            val = val.n
            err = val.s
        except AttributeError:
            pass

        return (val, err, unit)

    @staticmethod
    def unpack_quantity(data):
        val = data[0]
        if data[2] or data[1]:
            val = units.Quantity(data[0], data[2])
        if data[1]:
            val = val.plus_minus(data[1])
        return val

    @staticmethod
    def pack_histogram(hist):
        try:
            vals = hist.hist
            bins = hist.bin_edges
        except AttributeError:
            # this is not a histogram, no idea what to do with it
            return 0
        valunit = None
        binunit = None
        try:
            vals = vals.m
            valunit = vals.u
        except AttributeError:
            pass
        try:
            bins = bins.m
            binunit = bins.u
        except AttributeError:
            pass

        valerrs = unumpy.std_devs(vals)
        vals = unumpy.nominal_values(vals)
        # convert to npz
        args = dict(hist=vals, bins=bins, errs=valerrs)
        if not np.any(valerrs):
            del args['errs']

        buf = BytesIO()
        np.savez_compressed(buf, **args)
        doc = dict(hist=buf.getvalue())
        if valunit is not None:
            doc['hist_unit'] = valunit
        if binunit is not None:
            doc['bins_unit'] = binunit
        return doc

    @staticmethod
    def unpack_histogram(doc):
        if not isinstance(doc, dict):
            return doc
        data = np.load(BytesIO(doc['hist']))
        hist = data['hist']
        bins = data['bins']
        if 'errs' in data:
            hist = unumpy.uarray(hist, data['errs'])
        if 'hist_unit' in doc:
            hist = hist * units[doc['hist_unit']]
        if 'bins_unit' in doc:
            bins = bins * units[doc['bins_unit']]
        return Histogram(hist, bins)

    def writetocache(self, data):
        """ write an evaluated data dictionary to the cache """
        # TODO: currently the most granular level of caching is a single
        # match, which means if you only want to calculate a single spectrum,
        # you're out of luck. We should set it so you can do just one at a time
        if (not self.writecache) or (self.cache is None):
            return
        # make a shallow copy to avoid overwriting the original
        data = dict(**data)
        data['time'] = datetime.datetime.now()

        q = dict(modelid=data['modelid'],
                 componentid=data.get('componentid'),
                 specid=data.get('specid'),
                 matchid=data.get('matchid'))
        log.debug(f"Caching {q}")

        # repplace objects with cachable forms
        data['values'] = {key: self.pack_quantity(val)
                          for key, val in data.get('values', {}).items()}
        data['spectra'] = {key: self.pack_histogram(val)
                           for key, val in data.get('spectra', {}).items()}

        # write to db
        try:
            self.cache.insert_one(data)
        except pymongo.errors.DuplicateKeyError:
            log.warning(f"Existing entry for cache {q}")

    def readfromcache(self, component=None, spec=None, match=None,
                      projection={'spectrum_images': False}):
        """ Test if there is an entry in cache for the supplied values
        Returns:
            dict if in cache, None otherwise
        """
        if (self.bypasscache) or (self.cache is None):
            return None

        query = dict(modelid=self.model.id, componentid=None, specid=None,
                     matchid=None)
        if component is not None:
            query['componentid'] = component.id
        if spec is not None:
            query['specid'] = spec.id
        if match is not None:
            query['matchid'] = match.id

        doc = self.cache.find_one(query, projection)
        log.debug(f"Cached entry for {query}: {bool(doc)}")
        if not doc:
            return None
        # convert entries in raw to usable values
        for key, val in doc.get('values', {}).items():
            doc['values'][key] = self.unpack_quantity(val)
        for key, val in doc.get('spectra', {}).items():
            doc['spectra'][key] = self.unpack_histogram(val)

        return doc

def genevalcache(model, spawnprocess=True):
    """ Generate cache entries for eaach match, component, and spec in model
    Args:
        model (BgModel): the model to evaluate
        spawnprocess (bool): if true, launch a separate process
    Returns:
        multiprocessing.Process: if spawnprocess is true
        dict: evuated values for model otherwise
    """
    evaluator = ModelEvaluator(model)
    response = None
    if spawnprocess:
        proc = multiprocessing.Process(name='bgexplorer.genevalcache',
                                       target=lambda ev: ev.evalmodel(True),
                                       args=(evaluator,),
                                       daemon=True,
                                       )
        proc.start()
        response = proc
    else:
        response = evaluator.evalmodel(True)
    return response

def get_datatable(model):
    """ Get only the datatable for a model """
    dbview = copy.copy(utils.get_simsdbview(model=model))
    dbview.spectra = {}
    evaluator = ModelEvaluator(model, modeldb=utils.get_modeldb(),
                               genimages=False, simsdbview=dbview,
                               writecache=False)
    # with writecache=False, cache will never be written, even though
    # we're doing lots of calcuations. On the other hand, we're note
    # generating spectra, so if we write cache the spectra will *never*
    # be updated...
    # Maybe we should update cache rather than insert only?
    data = evaluator.evalmodel()
    return data['datatable']

def get_spectrum(model, specname, image=True, component=None, spec=None,
                 matches=None):
    """ Get only a single spectrum, ideally from cache """
    # see if `matches` is a single match
    match = None
    try:
        if len(matches) == 1:
            match = matches[0]
    except TypeError:
        match = match

    dbview = utils.get_simsdbview(model=model)
    spectra = {specname: dbview.spectra[specname]}
    dbview = copy.copy(dbview)
    dbview.values = {}
    dbview.spectra = spectra

    evaluator = ModelEvaluator(model, modeldb=utils.get_modeldb(),
                               genimages=image, simsdbview=dbview,
                               writecache=False)
    topkey = 'spectrum_images' if image else 'spectra'
    projection = {f'{topkey}.{specname}': True}
    cached = evaluator.readfromcache(component=component, spec=spec, match=match,
                                     projection=projection)
    if cached:
        try:
            return cached[topkey][specname]
        except KeyError:
            log.warn(f"Missing spectrum {specname} in eval cache")
            pass

    # now do evaluate...should we always just go for matches?
    # or should we just do everything and cache it?
    data = None
    if matches:
        data = evaluator.evalmatches(matches)
        data = evaluator.finalize(data)
    else:
        data = evaluator.evalmodel()
    try:
        return data[topkey][specname]
    except KeyError:
        # for whatever reason, the spectrum isn't there, so give none
        return None
