# python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from itertools import chain
import datetime
import gzip
import copy
import numpy as np
from uncertainties import unumpy
from io import BytesIO
from flask import abort
import pymongo
try:
    from matplotlib.figure import Figure
except ImportError:
    Figure = None

from .. import utils
from bgmodelbuilder import units
from bgmodelbuilder.simulationsdb.histogram import Histogram

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
            bypasscache: (bool)
        """
        self.model = model
        self.cache = None
        if modeldb and not modeldb.is_model_temp(model.id):
            self.cache = modeldb.getevalcache()

        self.genimages = genimages
        self.bypasscache = bypasscache
        self.writecache = writecache
        self.simsdbview = simsdbview
        if simsdbview is None:
            self.simsdbview = utils.getsimsdbview(model=model)
        self.simsdb = self.simsdbview.simsdb

    def evalmodel(self, fillallcache=False):
        cached = self.readfromcache()
        if cached:
            return cached

        log.debug(f"Starting evaluation of model {self.model.id}")

        # Loop through all the SimDataMatch objects and evaluate values and
        # spectra; create the sum data table
        databuf = BytesIO()
        datatable = gzip.GzipFile(mode='wb', fileobj=databuf)
        # write the datatable header

        def _valhead(val):
            suffix = ''
            if val in self.simsdbview.values_units:
                suffix = f' {self.simsdbview.values_units[val]}'
            return f'V_{val}{suffix}'
        datatable.write('\t'.join(chain(['ID'],
                                        (f'G_{g}' for g in self.simsdbview.groups),
                                        (_valhead(v)
                                         for v in self.simsdbview.values.values())
                                        ))+'\n')

        # now evaluate all matches
        data = self.evalmatches(
            self.model.simdata.values(), include_datatable=True)
        datatable.write(data['datatable']+'\n')

        # Complete the result object
        datatable.flush()
        data['datatable'] = databuf.getvalue()

        if self.cache is not None and fillallcache:
            for comp in self.model.getcomponents():
                self.evalcomponent(comp)
            for spec in self.model.getspecs(rootonly=True):
                self.evalspec(spec)

        self.finalize(data)
        log.debug(f"Finished evaluation of data for model {self.model.id}")
        return data

    def evalmatch(self, match):
        cached = self.readfromcache(match=match)
        if cached:
            return cached

        evals = self.simsdb.evaluate(chain(self.simsdbview.values.values(),
                                           self.simsdbview.spectra.values()),
                                     match)
        nvals = len(self.simsdbview.values)
        values = dict(zip(self.simsdbview.values.keys(), evals[:nvals]))
        spectra = dict(zip(self.simsdbview.spectra.keys(), evals[nvals:]))

        # convert spectra to requested units
        for specname, spectrum in spectra.values():
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
                                    self.simsdbview.evalgroups(match).value(),
                                    (_valtostr(k, v) for k, v in values.items())))

        data = dict(matchid=match.id, values=values, spectra=spectra,
                    datatable=datatable)
        self.finalize(data)
        return data

    def evalmatches(self, matches, include_datatable=False):
        data = dict(spectra=dict(), values=dict())
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

    def _add_data(self, data1, data2, include_datatable=False):
        spectra = dict((k, self.simsdbview.spectra[k].reduce(data1['spectra'].get(k),
                                                             data2['spectra'].get(k)))
                       for k in data1['spectra'])
        values = dict((k, self.simsdbview.values[k].reduce(data1['values'].get(k),
                                                           data2['values'].get(k)))
                      for k in data1['values'])

        result = dict(spectra=spectra, values=values)
        if include_datatable:
            datatable = '\n'.join(data1.get('datatable', ''),
                                  data2.get('datatable', ''))
            result['datatable'] = datatable
        return result

    def finalize(self, data, component=None, spec=None):
        data['modelid'] = self.model.id
        title = ''
        if component is not None:
            data['component'] = component.id
            title = f"Component={component.name}"
        if spec is not None:
            data['spec'] = spec.id
            title = f"Source={spec.name}"
        if self.genimages:
            self.make_all_images(data, title)
        self.writetocache(data)
        return data

    def make_all_images(self, data, titlesuffix=''):
        data['spectrum_images'] = {k: self.spectrum_image(k, v, titlesuffix)
                                   for k, v in data['spectra']}
        return data

    def spectrum_image(self, specname, spectrum, titlesuffix="",
                       logx=True, logy=True):
        unit = self.simsdbview.spectra_units.get(specname, None)
        if unit is not None:
            try:
                spectrum.hist.ito(unit)
            except AttributeError:  # not a quantity
                pass

        if Figure is None:
            abort(500, "Matplotlib is not available")
        log.debug("Generating spectrum image")
        # apparently this aborts sometimes?
        try:
            x = spectrum.bin_edges.m
        except AttributeError:
            x = spectrum.bin_edges
        fig = Figure()
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
        log.debug("Done generating image")
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
        vals = hist.hist
        bins = hist.bin_edges
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
        if (not self.writecache) or (self.cache is None):
            return
        # make a shallow copy to avoid overwriting the original
        data = dict(**data, time=datetime.datetime.now())

        # repplace objects with cachable forms
        for key, val in data.get('values', {}).items():
            data['values'][key] = self.pack_quantity(val)
        for key, val in data.get('spectra', {}).items():
            data['spectra'][key] = self.pack_histogram(val)

        # write to db
        try:
            self.cache.insert_one(data)
        except pymongo.errors.DuplicateKeyError:
            log.warning(f"Existing entry for cache {data}")

    def readfromcache(self, component=None, spec=None, match=None,
                      projection={'spectrum_images': False}):
        """ Test if there is an entry in cache for the supplied values
        Returns:
            dict if in cache, None otherwise
        """
        if (self.bypasscache) or (self.cache is None):
            return None

        query = dict(model=self.model.id)
        if component is not None:
            query['component'] = component.id
        if spec is not None:
            query['spec'] = spec.id
        if match is not None:
            query['match'] = match.id

        doc = self.cache.find_one(query)
        if not doc:
            return None
        # convert entries in raw to usable values
        for key, val in doc.get('values', {}).items():
            doc['values'][key] = self.unpack_quantity(val)
        for key, val in doc.get('spectra', {}).items():
            doc['spectra'][key] = self.unpack_histogram(val)

        return doc


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

    dbview = utils.get_simsdbview()
    spectra = dict(specname=dbview.spectra[specname])
    dbview = copy.copy(dbview)
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
    data = evaluator.evalmatches(matches) if matches else evaluator.evalmodel()
    return data[topkey][specname]
