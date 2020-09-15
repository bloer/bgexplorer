#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from itertools import chain
from flask import (Blueprint, render_template, request, abort, url_for, g,
                   Response, make_response, current_app)
import threading
import zlib
import json
import numpy as np
from uncertainties import unumpy
from math import ceil, log10
from io import BytesIO
try:
    from matplotlib.figure import Figure
except ImportError:
    Figure = None

from bson import ObjectId

from .. import utils
from ..dbview import SimsDbView

from . import billofmaterials as bomfuncs
from ..modeldb import InMemoryCacher

import logging
log = logging.getLogger(__name__)

from time import sleep

class ModelViewer(object):
    """Blueprint for inspecting saved model definitions
    Args:
        app:  The bgexplorer Flask object
        modeldb: a ModelDB object. If None, will get from the Flask object
        url_prefix (str): Where to mount this blueprint relative to root
    """
    defaultversion='HEAD'
    joinkey='___'

    def __init__(self, app=None, modeldb=None,
                 cacher=InMemoryCacher(), url_prefix='/explore'):
        self.app = app
        self._modeldb = modeldb

        self.bp = Blueprint('modelviewer', __name__,
                            static_folder='static',
                            template_folder='templates',
                            url_prefix='/<modelname>/<version>')

        self.bp.add_app_template_global(lambda : self, 'getmodelviewer')
        self.set_url_processing()
        self.register_endpoints()

        if self.app:
            self.init_app(app, url_prefix)

        self._threads = {}
        self._cacher = cacher
        #### User Overrides ####
        self.bomcols = bomfuncs.getdefaultcols()


    def init_app(self, app, url_prefix=''):
        """Register ourselves with the app"""
        app.register_blueprint(self.bp,
                               url_prefix=url_prefix+self.bp.url_prefix)
        app.extensions['ModelViewer'] = self



    @property
    def modeldb(self):
        return self._modeldb or utils.get_modeldb()

    @property
    def simsdb(self):
        return g.simsdbview.simsdb


    def set_url_processing(self):
        """process model objects into URL strings, and pre-load models
        into the `flask.g` object before passing to endpoint functions
        """
        def make_etag(model):
            """ Generate a string to use as an etag """
            try:
                return f"{model.id}-{model.editDetails['date']}"
            except AttributeError:
                # this should be a dictionary...
                return f"{model['_id']}-{model['editDetails']['date']}"

        @self.bp.after_request
        def addpostheaders(response):
            """ Add cache-control headers to all modelviewer responses """
            if self.app.config.get('NO_CLIENT_CACHE'):
                return
            # todo: add Last-Modified
            response.headers["Cache-Control"] = "private, max-age=100"
            try:
                response.headers['ETag'] = make_etag(g.model)
            except (AttributeError, KeyError): # model is not loaded in g
                pass
            return response

        @self.bp.url_defaults
        def add_model(endpoint, values):
            model = values.pop('model', None) or g.get('model', None)
            if model:
                #model could be object or dict
                name = getattr(model,'name', None) or model.get('name',None)
                version = getattr(model,'version', None)
                if version is None and hasattr(model,'get'):
                    version = model.get('version',None)
                values.setdefault('modelname', name)
                permalink = values.pop('permalink',None)
                if permalink is not None:
                    values['version'] = (version if permalink
                                         else self.defaultversion)
                else:
                    values.setdefault('version',
                                      version if not g.get('permalink')
                                      else self.defaultversion)
            elif 'modelid' in values:
                values['modelname'] = values.pop('modelid')
                values['version'] = '_'
                values['permalink'] = 1

            #transform components, specs into IDs
            if 'component' in values:
                values['componentid'] = values.pop('component').id
            if 'spec' in values:
                values['specid'] = values.pop('spec').getrootspec().id
            if 'match' in values:
                values['matchid'] = values.pop('match').id

        @self.bp.url_value_preprocessor
        def find_model(endpoint, values):
            # URL has different formats that result in different queries
            query = None
            if 'modelid' in values:
                query = values.pop('modelid')
            elif 'modelname' in values:
                query={'name': values.pop('modelname')}
                version = values.pop('version',self.defaultversion)
                if version == '_': #special, means name is actually ID
                    query['_id'] = query.pop('name')
                elif version != self.defaultversion:
                    query['version'] = version
            if not query:
                abort(400, "Incomplete model specification")

            # this function is called before `before_requests`, but we don't
            # want to extract the model if the client requested a cached
            # view. So we have to do the cache checking here
            etagreq = request.headers.get('If-None-Match')
            if etagreq and not self.app.config.get('NO_CLIENT_CACHE'):
                # construct the etag from the DB entry
                projection = {'editDetails.date': True}
                modeldict = self.modeldb.get_raw_model(query, projection)
                etag = make_etag(modeldict)
                if etagreq == etag:
                    abort(make_response('', '304 Not Modified',{'ETag': etag}))

            # if we get here, it's not in client cache
            g.model = utils.getmodelordie(query,self.modeldb)
            if version == self.defaultversion:
                g.permalink = url_for(endpoint, permalink=True,
                                      **values)
            g.simsdbview = utils.get_simsdbview(model=g.model)
            #construct the cached datatable in the background
            if self._cacher:
                self.build_datatable(g.model)


    def register_endpoints(self):
        """Define the view functions here"""

        @self.bp.route('/')
        def overview():
            history = self.modeldb.get_model_history(g.model.id)
            return render_template('overview.html', history=history)

        @self.bp.route('/component/')
        @self.bp.route('/component/<componentid>') #should be uuid type?
        def componentview(componentid=None):
            if componentid:
                component = utils.getcomponentordie(g.model, componentid)
                matches = g.model.getsimdata(component=component)
                datasets = sum((m.dataset or [] for m in matches), [])
                return render_template("componentview.html",
                                       component=component, datasets=datasets)
            else:
                return render_template("componentsoverview.html")


        @self.bp.route('/emissions/')
        def emissionsoverview():
            rootspecs = [ s for s in g.model.specs.values() if not s.parent]
            return render_template("emissionsoverview.html",
                                   rootspecs=rootspecs)

        @self.bp.route('/emission/<specid>')
        def emissionview(specid):
            spec = utils.getspecordie(g.model, specid)
            #find all simulation datasets associated to this spec
            matches = []
            if spec.getrootspec() == spec:
                matches = g.model.getsimdata(rootspec=spec)
            else:
                matches = g.model.getsimdata(spec=spec)
            datasets = sum((m.dataset or [] for m in matches), [])
            return render_template('emissionview.html', spec=spec,
                                   matches=matches, datasets=datasets)

        @self.bp.route('/simulations/')
        def simulationsoverview():
            return render_template("simulationsoverview.html")

        @self.bp.route('/queries/')
        def queriesoverview():
            #build a unique list of all queries
            queries = {}
            for m in g.model.getsimdata():
                key = str(m.query)
                if key not in queries:
                    queries[key] = []
                queries[key].append(m)

            return render_template('queriesoverview.html',queries=queries)

        @self.bp.route('/dataset/<dataset>')
        def datasetview(dataset):
            detail = self.simsdb.getdatasetdetails(dataset)
            return render_template("datasetview.html", dataset=dataset,
                                   detail = detail)

        @self.bp.route('/simdatamatch/<matchid>')
        def simdatamatchview(matchid):
            match = utils.getsimdatamatchordie(g.model, matchid)
            linkspec = match.spec.getrootspec()
            return render_template("simdatamatchview.html", match=match)


        @self.bp.route('/billofmaterials')
        def billofmaterials():
            bomrows = bomfuncs.getbomrows()
            return render_template("billofmaterials.html",
                                   bomrows=bomrows,
                                   bomcols=self.bomcols)

        @self.bp.route('/datatable')
        def datatable():
            """Return groups and values for all simdatamatches"""
            return self.get_datatable(g.model)

        @self.bp.route('/tables/default')
        def tablesdefault():
            """Show some default tables with the calculated rows"""
            return render_template("tablesdefault.html")

        @self.bp.route('/charts/default')
        def chartsdefault():
            """Show some default charts with the calculated rates"""
            return render_template("chartsdefault.html")

        @self.bp.route('/spectra/default')
        def spectradefault():
            return render_template("spectradefault.html")

        @self.bp.route('/export')
        def export():
            """Present the model as a JSON document"""
            d = g.model.todict()
            #replace ObjectIds with strings
            if isinstance(d.get('_id'), ObjectId):
                d['_id'] = str(d['_id'])
            if isinstance(d.get('derivedFrom'), ObjectId):
               d['derivedFrom'] = str(d['derivedFrom'])
            return Response(json.dumps(d), mimetype="application/json")

        @self.bp.route('/getspectrum')
        @self.bp.route('/getspectrum/<specname>')
        def getspectrum(specname=None):
            # get the generator for the spectrum
            if not specname:
                valname = request.args.get('val')
                if not valname:
                    abort(404, "Either spectrum name or value name is required")
                specname = g.simsdbview.values_spectra.get(valname)
                if not specname:
                    # valname might have a unit suffix applied to it
                    index = valname.rfind(' [')
                    valname = valname[:index]
                    specname = g.simsdbview.values_spectra.get(valname)
                if not specname:
                    abort(404, f"No spectrum associated to value '{valname}'")
            speceval = g.simsdbview.spectra.get(specname)
            if speceval is None:
                abort(404, f"No spectrum generator for '{specname}'")

            log.debug(f"Generating spectrum: {specname}")
            title = specname
            # get the matches
            matches = request.args.getlist('m')
            try:
                matches = [g.model.simdata[m] for m in matches]
            except KeyError:
                abort(404, "Request for unknown sim data match")
            if not matches:
                # matches may be filtered by component or spec
                component = None
                if 'componentid' in request.args:
                    component = utils.getcomponentordie(g.model,
                                                        request.args['componentid'])
                    title += ", Component = "+component.name
                rootspec = None
                if 'specid' in request.args:
                    rootspec = utils.getspecordie(g.model,
                                                  request.args['specid'])
                    title += ", Source = "+rootspec.name
                matches = g.model.getsimdata(rootcomponent=component, rootspec=rootspec)

            # test for a group filter
            groupname = request.args.get('groupname')
            groupval = request.args.get('groupval')
            if groupname and groupval and groupval != 'Total':
                try:
                    groupfunc = g.simsdbview.groups[groupname]
                except KeyError:
                    abort(404, f"No registered grouping function {groupname}")
                def _filter_group(match):
                    mgval = g.simsdbview.evalgroup(match, groupname, False)
                    return g.simsdbview.is_subgroup(mgval, groupval)
                matches = list(filter(_filter_group, matches))
                title += ", "+groupname+" = "
                title += '/'.join(g.simsdbview.unflatten_gval(groupval, True))

            if not matches:
                abort(404, "No sim data matching query")

            spectrum = self.simsdb.evaluate([speceval], matches)[0]
            if not hasattr(spectrum, 'hist') or not hasattr(spectrum, 'bin_edges'):
                abort(500, f"Error generating spectrum, got {type(spectrum)}")

            unit = g.simsdbview.spectra_units.get(specname, None)
            if unit is not None:
                try:
                    spectrum.hist.ito(unit)
                except AttributeError: #not a quantity
                    pass

            fmt = request.args.get("format", "png").lower()
            response = None
            if fmt == 'tsv':
                response = Response(self.streamspectrum(spectrum, sep='\t'),
                                    mimetype='text/tab-separated-value')
            elif fmt == 'csv':
                response = Response(self.streamspectrum(spectrum, sep=','),
                                    mimetype='text/csv')
            elif fmt == 'png':
                response = self.specimage(spectrum, title=title)
            else:
                abort(400, f"Unhandled format specifier {fmt}")

            return response

    def streamspectrum(self, spectrum, sep=',', include_errs=True,
                       fmt='{:.5g}'):
        """ Return a generator response for a spectrum
        Args:
            spectrum (Histogram): spectrum to stream
            sep (str): separator (e.g. csv or tsv)
            include_errs (bool): if True, include a column for errors
            fmt (str): format specifier
        Returns:
            generator to construct Response
        """
        bins, vals =  spectrum.bin_edges, spectrum.hist
        vals_has_units = hasattr(vals, 'units')
        bins_has_units = hasattr(bins, 'units')

        # yield the header
        head = ["Bin", "Value"]
        if bins_has_units:
            head[0] += f' [{bins.units}]'
        if vals_has_units:
            head[1] += f' [{vals.units}]'
        if include_errs:
            head.append('Error')
        yield sep.join(head)+'\n'

        # now remove units and extract errors
        if vals_has_units:
            vals = vals.m
        if bins_has_units:
            bins = bins.m
        vals, errs = unumpy.nominal_values(vals), unumpy.std_devs(vals)

        for abin, aval, anerr in zip(bins, vals, errs):
            yield sep.join((str(abin), fmt.format(aval), fmt.format(anerr)))+'\n'

    def specimage(self, spectrum, title=None, logx=True, logy=True):
        """ Generate a png image of a spectrum
        Args:
            spectrum (Histogram): spectrum to plot
            title (str): title
            logx (bool): set x axis to log scale
            logy (bool): set y axis to log scale
        Returns:
            a Response object
        """
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
        ax.set_title(title)
        if logx:
            ax.set_xscale('log')
        if logy:
            ax.set_yscale('log')
        if hasattr(spectrum.bin_edges, 'units'):
            ax.set_xlabel(f'Bin [{spectrum.bin_edges.units}]')
        if hasattr(spectrum.hist, 'units'):
            ax.set_ylabel(f"Value [{spectrum.hist.units}]")

        """
        #limit to at most N decades...
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
        log.debug("Rendering...")
        out = BytesIO()
        fig.savefig(out, format='png')
        log.debug("Done generating image")
        size = out.tell()
        out.seek(0)
        res = Response(out.getvalue(),
                       content_type='image/png',
                       headers={'Content-Length': size,
                                'Content-Disposition': 'inline',
                                },
                       )
        return res




    #need to pass simsdb because it goes out of context
    def streamdatatable(self, model, simsdbview=None):
        """Stream exported data table so it doesn't all go into mem at once
        """
        log.debug(f"Generating data table for model {model.id}")
        #can't evaluate values if we don't have a simsdb
        if simsdbview is None:
            simsdbview = utils.get_simsdbview(model=model) or SimsDbView()
        simsdb = simsdbview.simsdb
        valitems = list(simsdbview.values.values())
        matches = model.simdata.values()
        #send the header
        valheads = ['V_'+v+(' [%s]'%simsdbview.values_units[v]
                            if v in simsdbview.values_units else '')
                    for v in simsdbview.values]
        yield('\t'.join(chain(['ID'],
                              ('G_'+g for g in simsdbview.groups),
                              valheads))
              +'\n')
        #loop through matches
        for match in matches:
            evals = []
            if valitems:
                evals = simsdb.evaluate(valitems, match)
                for index, vlabel in enumerate(simsdbview.values):
                    # convert to unit if provided
                    unit = simsdbview.values_units.get(vlabel,None)
                    if unit:
                        try:
                            evals[index] = evals[index].to(unit).m
                        except AttributeError: #not a Quantity...
                            pass
                    # convert to string
                    evals[index] = "{:.3g}".format(evals[index])
                    if match.spec.islimit:
                        evals[index] = '<'+evals[index]
            groupvals = (g(match) for g in simsdbview.groups.values())
            groupvals = (simsdbview.groupjoinkey.join(g)
                         if isinstance(g,(list,tuple)) else g
                         for g in groupvals)
            yield('\t'.join(chain([match.id],
                                  (str(g) for g in groupvals),
                                  evals))
                  +'\n')
            #sleep(0.2) # needed to release the GIL
        log.debug(f"Finished generating data table for model {model.id}")



    @staticmethod
    def datatablekey(model):
        return "datatable:"+str(model.id)

    def build_datatable(self, model):
        """Generate a gzipped datatable and cache it
        Args:
            model: a BgModel

        Returns:
            None if no cacher is defined
            0 if the result is already cached
            Thread created to generate the cache otherwise
        """
        #don't bother to call if we don't have a cache
        if not self._cacher:
            return None

        #TODO: self._threads and self._Cacher should probably be mutexed
        #see if there's already a worker
        key = self.datatablekey(model)
        if key in self._threads:
            return self._threads[key]
        #see if it's already cached
        if self._cacher.test(key):
            return 0

        #if we get here, we need to generate it
        def cachedatatable(dbview):
            compressor = zlib.compressobj()
            res = b''.join(compressor.compress(s.encode('utf-8'))
                           for s in self.streamdatatable(model, dbview))
            res += compressor.flush()
            self._cacher.store(key, res)
            self._threads.pop(key) #is this a bad idea???
        dbview = utils.get_simsdbview(model=model)
        thread = threading.Thread(target=cachedatatable,name=key,
                                  args=(dbview,))
        self._threads[key] = thread
        thread.start()
        return thread

    def get_datatable(self, model):
        """Return a Result object with the encoded or streamed datatable"""
        key = self.datatablekey(model)
        if not self._cacher or self.modeldb.is_model_temp(model.id):
            #no cache, so stream it directly, don't bother to zip it
            #should really be text/csv, but then browsersr won't let you see it
            return Response(self.streamdatatable(model), mimetype='text/plain')

        if not self._cacher.test(key):
            thread = self.build_datatable(model)
            if thread:
                thread.join() #wait until it's done
        res = self._cacher.get(key)
        if not res:
            abort(500,"Unable to generate datatable")
        return Response(res, headers={'Content-Type':'text/plain;charset=utf-8',
                                      'Content-Encoding':'deflate',
                                      })


    def get_componentsort(self, component, includeself=True):
        """Return an array component names in assembly order to be passed
        to the javascript analyzer for sorting component names
        """
        #TODO: cache this
        result = [component.name] if includeself  else []
        for child in component.getcomponents(merge=False):
            branches = self.get_componentsort(child)
            if includeself:
                branches = [self.joinkey.join((component.name, s))
                            for s in branches]
            result.extend(branches)
        return result


    def get_groupsort(self):
        res = dict(**g.simsdbview.groupsort)
        #todo: set up provided lists
        if 'Component' not in res:
            res['Component'] = self.get_componentsort(g.model.assemblyroot, False)
        return res

    def eval_matches(self, matches, dovals=True, dospectra=False):
        """ Evaluate `matches` for all registered values and specs
        Args:
            matches: list of SimDataMatch objects to evaluate
            dovals (bool): include entries from `self.values` ?
            dospectra (bool): include entries from `self.spectra` ?
        Returns:
            values (dict): dictionary mapping of keys in `self.values` and
                           `self.spectra` to evaluated results. If a key in
                           `spectra` conflicts with one in values, it will be
                           renamed to "spectrum_<key>"
        """
        # this no longer works, but wasn't used. Keep around for now...
        raise NotImplementedError()

        vals = dict(**self.values) if dovals else {}
        if dospectra:
            for key, spectrum in self.spectra.items():
                if key in vals:
                    key = f'spectrum_{key}'
                vals[key] = spectrum
        result =  dict(zip(vals.keys(),
                           self.simsdb.evaluate(vals.values(), matches)))
        if dovals:
            for key, unit in self.values_units.items():
                try:
                    result[key].ito(unit)
                except AttributeError:
                    pass
        if dospectra:
            for key, unit in self.spectra_units.items():
                if dovals and key in self.values:
                    key = f'spectrum_{key}'
                try:
                    result[key].ito(unit)
                except AttributeError:
                    pass
        return result

