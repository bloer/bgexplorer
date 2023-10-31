# python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from flask import (Blueprint, render_template, request, abort, url_for, g,
                   Response, make_response, redirect, flash)
import json
import functools
from uncertainties import unumpy
from bson import ObjectId

from .. import utils
from .evaldata import get_spectrum, get_datatable, getcachestatus, genevalcache
from . import billofmaterials as bomfuncs
from ..modeldb import InMemoryCacher

import logging
log = logging.getLogger(__name__)


def make_etag(model):
    """ Generate a string to use as an etag """
    try:
        return f"{model.id}-{model.editDetails['date']}"
    except AttributeError:
        # this should be a dictionary...
        return f"{model['_id']}-{model['editDetails']['date']}"

# todo: add a 'get_cache_status' and 'build_cache' functions


class ModelViewer(object):
    """Blueprint for inspecting saved model definitions
    Args:
        app:  The bgexplorer Flask object
        modeldb: a ModelDB object. If None, will get from the Flask object
        url_prefix (str): Where to mount this blueprint relative to root
    """
    defaultversion = 'HEAD'
    joinkey = '___'

    def __init__(self, app=None, modeldb=None,
                 cacher=InMemoryCacher(), url_prefix='/explore'):
        self.app = app
        self._modeldb = modeldb

        self.bp = Blueprint('modelviewer', __name__,
                            static_folder='static',
                            template_folder='templates',
                            url_prefix='/<modelname>/<version>')

        self.bp.add_app_template_global(lambda: self, 'getmodelviewer')
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

        @self.bp.after_request
        def addpostheaders(response):
            """ Add cache-control headers to all modelviewer responses """
            if self.app.config.get('NO_CLIENT_CACHE'):
                return
            # todo: add Last-Modified
            if 'Cache-Control' not in response.headers:
                response.headers["Cache-Control"] = "private, max-age=100"
                try:
                    response.headers['ETag'] = make_etag(g.model)
                except (AttributeError, KeyError):  # model is not loaded in g
                    pass
            return response

        @self.bp.url_defaults
        def add_model(endpoint, values):
            model = values.pop('model', None) or g.get('model', None)
            if model:
                # model could be object or dict
                name = getattr(model, 'name', None) or model.get('name', None)
                version = getattr(model, 'version', None)
                if version is None and hasattr(model, 'get'):
                    version = model.get('version', None)
                values.setdefault('modelname', name)
                permalink = values.pop('permalink', None)
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

            # transform components, specs into IDs
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
                query = {'name': values.pop('modelname')}
                version = values.pop('version', self.defaultversion)
                if version == '_':  # special, means name is actually ID
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
                    abort(make_response(
                        '', '304 Not Modified', {'ETag': etag}))

            # if we get here, it's not in client cache
            g.model = utils.getmodelordie(query, self.modeldb)
            if version == self.defaultversion:
                g.permalink = url_for(endpoint, permalink=True,
                                      **values)
            g.simsdbview = utils.get_simsdbview(model=g.model)

    def excludetemp(self, endpoint):
        """ Decorator for endpoints that should not be processed for temp
        models: generating spectra, etc """
        @functools.wraps(endpoint)
        def _wrapper(*args, **kwargs):
            model = getattr(g, 'model', None)
            if model and self.modeldb.is_model_temp(model.id):
                abort(404, "Resource not available for temporary models")
            return endpoint(*args, **kwargs)
        return _wrapper

    def nocache(self, endpoint):
        """ prevent cache """
        @functools.wraps(endpoint)
        def _wrapper(*args, **kwargs):
            response = make_response(endpoint(*args, **kwargs))
            response.headers['Cache-Control'] = "no-store, max-age=0"
            return response
        return _wrapper

    def register_endpoints(self):
        """Define the view functions here"""

        @self.bp.route('/')
        def overview():
            history = self.modeldb.get_model_history(g.model.id)
            return render_template('overview.html', history=history)

        @self.bp.route('/component/')
        @self.bp.route('/component/<componentid>')  # should be uuid type?
        def componentview(componentid=None):
            if componentid:
                component = utils.getcomponentordie(g.model, componentid)
                matches = g.model.getsimdata(component=component)
                datasets = []
                for m in matches:
                    if isinstance(m.dataset, (list, tuple)):
                        datasets.extend(m.datataset)
                    elif m.dataset is not None:
                        datasets.append(m.dataset)
                #datasets = sum((m.dataset or [] for m in matches), [])
                return render_template("componentview.html",
                                       component=component, datasets=datasets)
            else:
                return render_template("componentsoverview.html")

        @self.bp.route('/emissions/')
        def emissionsoverview():
            rootspecs = [s for s in g.model.specs.values() if not s.parent]
            return render_template("emissionsoverview.html",
                                   rootspecs=rootspecs)

        @self.bp.route('/emission/<specid>')
        def emissionview(specid):
            spec = utils.getspecordie(g.model, specid)
            # find all simulation datasets associated to this spec
            matches = []
            if spec.getrootspec() == spec:
                matches = g.model.getsimdata(rootspec=spec)
            else:
                matches = g.model.getsimdata(spec=spec)
            datasets = []
            for m in matches:
                if isinstance(m.dataset, (list, tuple)):
                    datasets.extend(m.datataset)
                elif m.dataset is not None:
                    datasets.append(m.dataset)
            #datasets = sum((m.dataset or [] for m in matches), [])
            return render_template('emissionview.html', spec=spec,
                                   matches=matches, datasets=datasets)

        @self.bp.route('/simulations/')
        def simulationsoverview():
            return render_template("simulationsoverview.html")

        @self.bp.route('/queries/')
        def queriesoverview():
            # build a unique list of all queries
            queries = {}
            for m in g.model.getsimdata():
                key = str(m.query)
                if key not in queries:
                    queries[key] = []
                queries[key].append(m)

            return render_template('queriesoverview.html', queries=queries)

        @self.bp.route('/dataset/<dataset>')
        def datasetview(dataset):
            detail = self.simsdb.getdatasetdetails(dataset)
            return render_template("datasetview.html", dataset=dataset,
                                   detail=detail)

        @self.bp.route('/simdatamatch/<matchid>')
        def simdatamatchview(matchid):
            match = utils.getsimdatamatchordie(g.model, matchid)
            linkspec = match.spec.getrootspec()
            values = {}
            if match.emissionrate:
                vals = g.simsdbview.values
                values_units = g.simsdbview.values_units
                evaluated = self.simsdb.evaluate(list(vals.values()), match)
                iter_ = (zip(vals, evaluated) if isinstance(evaluated, list)
                         else evaluated.items())
                for k, v in iter_:
                    try:
                        values[k] = v.to(values_units[k])/match.emissionrate.to('Bq')
                    except IndexError:
                        # key is not in values_units
                        values[k] = v / match.emissionrate.to('Bq')
                    except Exception:
                        values[k] = -1
            return render_template("simdatamatchview.html", match=match,
                                   linkspec=linkspec, values=values)

        @self.bp.route('/billofmaterials')
        def billofmaterials():
            bomrows = bomfuncs.getbomrows()
            return render_template("billofmaterials.html",
                                   bomrows=bomrows,
                                   bomcols=self.bomcols)

        @self.bp.route('/clearcache', methods=('POST',))
        @self.excludetemp
        def clearcache():
            self.modeldb.clearevalcache(g.model.id)
            flash("Cleared evaluated data cache for model %s" % g.model.id,
                  'success')
            genevalcache(g.model)
            return redirect(url_for('.overview'))

        @self.bp.route('/gencache', methods=('POST',))
        @self.excludetemp
        def gencache():
            genevalcache(g.model)
            return redirect(url_for('.overview'))

        @self.bp.route('/datatable')
        @self.excludetemp
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
            # replace ObjectIds with strings
            if isinstance(d.get('_id'), ObjectId):
                d['_id'] = str(d['_id'])
            if isinstance(d.get('derivedFrom'), ObjectId):
                d['derivedFrom'] = str(d['derivedFrom'])
            return Response(json.dumps(d), mimetype="application/json")

        @self.bp.route('/getspectrum')
        @self.bp.route('/getspectrum/<specname>')
        @self.excludetemp
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
            #if specname not in g.simsdbview.spectra:
            #    abort(404, f"No spectrum generator for '{specname}'")

            #log.debug(f"Generating spectrum: {specname}")
            # get the matches
            matches = request.args.getlist('m')
            component = None
            spec = None
            if 'componentid' in request.args:
                component = utils.getcomponentordie(g.model,
                                                    request.args['componentid'])
            if 'specid' in request.args:
                spec = utils.getspecordie(g.model, request.args['specid'])

            try:
                matches = [g.model.simdata[m] for m in matches]
            except KeyError:
                abort(404, "Request for unknown sim data match")

            # test for a group filter
            groupname = request.args.get('groupname')
            groupval = request.args.get('groupval')
            if groupname and groupval and groupval != g.simsdbview.groupjoinkey:
                if not matches:
                    matches = g.model.getsimdata(rootcomponent=component,
                                                 rootspec=spec)
                if groupname not in g.simsdbview.groups:
                    abort(404, f"No registered grouping function {groupname}")

                def _filter_group(match):
                    mgval = g.simsdbview.evalgroup(match, groupname, False)
                    return g.simsdbview.is_subgroup(mgval, groupval)
                matches = list(filter(_filter_group, matches))
                if not matches:
                    abort(404, "No sim data matching query")

            fmt = request.args.get("format", "png").lower()
            spectrum = get_spectrum(g.model, specname, image=(fmt == 'png'),
                                    component=component, spec=spec,
                                    matches=matches)
            if spectrum is None:
                abort(404, "Unable to generate spectrum")

            response = None
            if fmt == 'tsv':
                response = Response(self.streamspectrum(spectrum, sep='\t'),
                                    mimetype='text/tab-separated-value')
            elif fmt == 'csv':
                response = Response(self.streamspectrum(spectrum, sep=','),
                                    mimetype='text/csv')
            elif fmt == 'png':
                response = Response(spectrum, content_type='image/png',
                                    headers={'Content-Length': len(spectrum),
                                             'Content-Disposition': 'inline',
                                             })
            else:
                abort(400, f"Unhandled format specifier {fmt}")

            return response

        @self.bp.route('/cachestatus')
        @self.excludetemp
        @self.nocache
        def cachestatus():
            # do we need to explicitly jsonify this?
            return getcachestatus(g.model)

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
        bins, vals = spectrum.bin_edges, spectrum.hist
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

    @staticmethod
    def datatablekey(model):
        return "datatable:"+make_etag(model)

    def get_datatable(self, model):
        """Return a Result object with the encoded or streamed datatable"""
        return Response(get_datatable(model),
                        headers={'Content-Type': 'text/plain;charset=utf-8',
                                 'Content-Encoding': 'gzip',
                                 })

    def get_componentsort(self, component, includeself=True):
        """Return an array component names in assembly order to be passed
        to the javascript analyzer for sorting component names
        """
        # TODO: cache this
        result = [component.name] if includeself else []
        for child in component.getcomponents(merge=False):
            branches = self.get_componentsort(child)
            if includeself:
                branches = [self.joinkey.join((component.name, s))
                            for s in branches]
            result.extend(branches)
        return result

    def get_groupsort(self):
        res = dict(**g.simsdbview.groupsort)
        # todo: set up provided lists
        if 'Component' not in res:
            res['Component'] = self.get_componentsort(
                g.model.assemblyroot, False)
        return res
