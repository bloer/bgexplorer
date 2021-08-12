from itertools import chain
import datetime
import gzip
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

# todo: take component, spec, groupname, groupval? with class?


class ModelEvaluator(object):
    """ Utiilty class to generate data tables and spectra for non-temp models """

    def __init__(self, model, modeldb=None, simsdbview=None,
                 bypasscache=False, writecache=True, cacheimages=True):
        """ Constructor
        Args:
            model (BgModel): model object to evaluate
            modeldb (ModelDB): database with models
            simsdbview (SimsDbView): defines vals and spectra
            bypasscache (bool): If True, do not search for cached value
            writecache (bool): If False, do not write calculation results to cache
            cacheimages (bool): If False, don't cache image generation
        """
        self.model = model
        self.cache = None
        if not modeldb:
            modeldb = utils.get_modeldb()
        if modeldb and not modeldb.is_model_temp(model.id):
            self.cache = modeldb.getevalcache()

        self.bypasscache = bypasscache
        self.writecache = writecache
        self.cacheimages = cacheimages
        self.simsdbview = simsdbview
        if simsdbview is None:
            self.simsdbview = utils.get_simsdbview(model=model)
        self.simsdb = self.simsdbview.simsdb

    def _valtostr(self, valname, val, match):
        # convert to unit if provided
        unit = self.simsdbview.values_units.get(valname, None)
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

    def _evalmatch(self, match, dovals=True, dogroups=True, dospectra=False):
        """ Evaluate SimDocEvals and grous for a match
        Returns:
            dict
        """
        toeval = []
        if dovals:
            toeval.extend(self.simsdbview.values.values())
        if dospectra:
            toeval.extend(self.simsdbview.spectra.values())
        result = self.simsdb.evaluate(toeval, match)

        doc = dict()
        if dovals:
            doc['values'] = [self._valtostr(name, val, match) for name, val in
                             zip(self.simsdbview.values.keys(), result)]
            result = result[len(self.simsdbview.values):]
        if dospectra:
            doc['spectra'] = result

        if dogroups:
            doc['groups'] = self.simsdbview.evalgroups(match).values()

        return doc

    def datatable(self, doallcache=False):
        """ Generate the datatable with line for each sim data match,
        return the result as a gzip compressed blob
        Args:
            doallcache (bool): If True, while evaluating all values, also
                               generate spectra. This slows down datatable
                               generation, but speeds up caching speed overall
        """
        cached = self.readfromcache("datatable")
        if cached is not None:
            return cached

        start = time.monotonic()
        log.info(f"Generating datatable for model {self.model.id}")
        # define some useful helper functions

        def _valhead(val):
            suffix = ''
            if val in self.simsdbview.values_units:
                suffix = f' [{self.simsdbview.values_units[val]}]'
            return f'V_{val}{suffix}'

        # prepare output buffer
        buf = BytesIO()
        datatable = gzip.open(buf, mode='wt', newline='\n')

        # write the header
        header = '\t'.join(chain(['ID'],
                                 (f'G_{g}' for g in self.simsdbview.groups),
                                 (_valhead(v)
                                  for v in self.simsdbview.values.keys())
                                 ))
        datatable.write(header)
        datatable.write('\n')
        for match in self.model.simdata.values():
            doc = self._evalmatch(match, dovals=True, dogroups=True,
                                  dospectra=doallcache)
            dtline = '\t'.join(chain([match.id],
                                     [str(g) for g in doc['groups']],
                                     doc['values']))
            datatable.write(dtline)
            datatable.write('\n')
            if doallcache:
                for name, spec in zip(self.simsdbview.spectra, doc['spectra']):
                    self.writetocache(name, spec, match=match, fmt='hist')

        datatable.flush()
        result = buf.getvalue()
        self.writetocache('datatable', result)
        log.info("Finished evaluation of data for model %s in %s seconds",
                 self.model.id, time.monotonic()-start)
        return result

    def spectrum(self, specname, component=None, spec=None, match=None,
                 matches=None):
        return self._spectrum_impl(specname, component, spec, match, matches,
                                   fmt="hist")

    def spectrum_image(self, specname, component=None, spec=None, match=None,
                       matches=None):
        return self._spectrum_impl(specname, component, spec, match, matches,
                                   fmt="png")

    def fillallcache(self, genimages=False):
        """ Loop over all matches, components, and spectra in the model and
        create cache entries for all spectra
        Args:
            genimages (bool): If True, also generate PNG images
        """
        if not self.cacheimages:
            genimages = False
        start = time.monotonic()
        log.info(f"Generating full cache for model {self.model.id}")
        self.datatable(doallcache=True)

        specfunc = self.spectrum_image if genimages else self.spectrum

        for specname in self.simsdbview.spectra:
            for match in self.model.getsimdata():
                specfunc(specname, match=match)
            for comp in self.model.getcomponents():
                specfunc(specname, component=comp)
            for spec in self.model.getspecs(rootonly=True):
                specfunc(specname, spec=spec)
            # also gen the top-level model hists
            specfunc(specname)
        log.info("Finished caching data for model %s in %s seconds",
                 self.model.id, time.monotonic()-start)

    def _spectrum_impl(self, specname, component=None, spec=None, match=None,
                       matches=None, fmt="hist"):
        cacheable = (not matches)
        result = None
        fmt = fmt.lower()
        if cacheable:
            cached = self.readfromcache(specname, component=component,
                                        spec=spec, match=match, fmt=fmt)
            if cached is not None:
                return cached

        if specname not in self.simsdbview.spectra:
            raise KeyError(f"Unknown spectrum generator {specname}")

        if fmt == 'png':
            result = self._spectrum_impl(specname, component, spec, match,
                                         matches, fmt="hist")
            titlesuffix = ''
            if component is not None:
                titlesuffix += f', Component={component.name}'
            if spec is not None:
                titlesuffix += f', Source={spec.name}'
            result = self._spectrum_image(specname, result, titlesuffix)

        elif match is not None:
            result = self._spectrum_hist(specname, match)

        else:
            if not matches:
                matches = self.model.getsimdata(rootcomponent=component,
                                                rootspec=spec)
            result = None
            reducer = self.simsdbview.spectra[specname].reduce
            for amatch in matches:
                result1 = self._spectrum_impl(specname, match=amatch, fmt=fmt)
                result = try_reduce(reducer, result, result1)

        if cacheable:
            self.writetocache(specname, result, component=component, spec=spec,
                              match=match, fmt=fmt)

        return result

    def _spectrum_hist(self, specname, match):
        specgen = self.simsdbview.spectra[specname]
        result = self.simsdb.evaluate(specgen, match)[0]
        unit = self.simsdbview.spectra_units.get(specname, None)
        if unit is not None:
            try:
                result.hist.ito(unit)
            except AttributeError:  # not a quantity
                pass
        return result

    def _spectrum_image(self, specname, spectrum, titlesuffix="",
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
            doc['hist_unit'] = str(valunit)
        if binunit is not None:
            doc['bins_unit'] = str(binunit)
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

    def writetocache(self, dataname, result, component=None, spec=None,
                     match=None, fmt=None):
        """ write an evaluated data dictionary to the cache """
        # TODO: currently the most granular level of caching is a single
        # match, which means if you only want to calculate a single spectrum,
        # you're out of luck. We should set it so you can do just one at a time
        if (not self.writecache) or (self.cache is None) or (result is None):
            return

        if fmt == 'png' and not self.cacheimages:
            return

        if dataname != 'datatable' and fmt not in ('hist', 'png'):
            raise ValueError("Only 'hist' and 'png' fmt supported for spectra")

        if fmt == 'hist':
            result = self.pack_histogram(result)

        entry = dict(modelid=self.model.id, dataname=dataname, fmt=fmt,
                     time=datetime.datetime.now(), data=result)
        if dataname != 'datatable':
            if component is not None:
                entry['componentid'] = component.id
            if spec is not None:
                entry['specid'] = spec.id
            if match is not None:
                entry['matchid'] = match.id

        query = {k: str(v) for k, v in entry.items()
                 if k not in ('data', 'time')}
        log.debug(f"Caching {query}")

        # write to db
        try:
            self.cache.insert_one(entry)
        except pymongo.errors.DuplicateKeyError:
            del entry['data']
            log.warning(f"Existing entry for cache {query}")

    def readfromcache(self, dataname, component=None, spec=None,
                      match=None, fmt=None):
        """ Test if there is an entry in cache for the supplied values
        Returns:
            obj if in cache, None otherwise
        """
        if (self.bypasscache) or (self.cache is None):
            return None

        query = dict(modelid=self.model.id, dataname=dataname, fmt=fmt,
                     componentid=None, specid=None,  matchid=None)
        if component is not None:
            query['componentid'] = component.id
        if spec is not None:
            query['specid'] = spec.id
        if match is not None:
            query['matchid'] = match.id

        doc = self.cache.find_one(query, projection={'data': True})
        log.debug(f"Cached entry for {query}: {bool(doc)}")
        if not doc:
            return None
        try:
            data = doc['data']
        except KeyError:
            log.warn("No 'data' key in cached doc for query %s", query)
            return None
        if fmt == 'hist':
            data = self.unpack_histogram(data)
        return data


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
                                       target=lambda ev: ev.fillallcache(),
                                       args=(evaluator,),
                                       daemon=True,
                                       )
        proc.start()
        response = proc
    else:
        response = evaluator.fillallcache()
    return response


def get_datatable(model):
    """ Get only the datatable for a model """
    return ModelEvaluator(model).datatable()


def get_spectrum(model, specname, image=True, component=None, spec=None,
                 matches=None):
    """ Get only a single spectrum, ideally from cache """
    # see if `matches` is a single match
    match = None
    try:
        if len(matches) == 1:
            match = matches[0]
            matches = None
    except TypeError:
        pass

    evaluator = ModelEvaluator(model)
    if image:
        result = evaluator.spectrum_image(specname, component, spec, match,
                                          matches)
    else:
        result = evaluator.spectrum(specname, component, spec, match, matches)
    return result
