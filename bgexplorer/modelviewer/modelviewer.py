#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from itertools import chain
from flask import (Blueprint, render_template, request, abort, url_for, g, 
                   Response)
from .. import utils

from . import billofmaterials as bomfuncs


class ModelViewer(object):
    """Blueprint for inspecting saved model definitions
    Args:
        app:  The bgexplorer Flask object
        modeldb: a ModelDB object. If None, will get from the Flask object
        simsdb:  a SimulationsDB object. If None, will get from the Flask object
        url_prefix (str): Where to mount this blueprint relative to root
        groups (dict): Grouping functions to evaluate for all simdatamatches
        values (dict): Value functions to evaluate for all simdatamatches
    """
    defaultversion='HEAD'
    
    def __init__(self, app=None, modeldb=None, simsdb=None,
                 url_prefix='/explore', groups=None, values=None, 
                 values_units=None):
        self.app = app
        self._modeldb = modeldb
        self._simsdb = simsdb
        
        self.bp = Blueprint('modelviewer', __name__,
                            static_folder='static', 
                            template_folder='templates',
                            url_prefix='/<modelname>/<version>')
        
            
        self.set_url_processing()
        self.register_endpoints()
        
        if self.app:
            self.init_app(app, url_prefix)

            
        self.groups = groups or {}
        self.values = values or {}
        self.values_units = values_units or {}

        #### User Overrides ####
        self.bomcols = bomfuncs.getdefaultcols()
            
    def init_app(self, app, url_prefix=''):
        """Register ourselves with the app"""
        app.register_blueprint(self.bp, 
                               url_prefix=url_prefix+self.bp.url_prefix)
        

    @property
    def modeldb(self):
        return self._modeldb or utils.get_modeldb()

    @property
    def simsdb(self):
        return self._simsdb or utils.get_simsdb()
        

    def set_url_processing(self):
        """process model objects into URL strings, and pre-load models 
        into the `flask.g` object before passing to endpoint functions
        """
        @self.bp.url_defaults
        def add_model(endpoint, values):
            model = values.pop('model', None) or g.get('model', None)
            if model:
                #model could be object or dict
                name = getattr(model,'name', None) or model.get('name',None)
                version = (getattr(model,'version', None) 
                           or model.get('version',None))
                values.setdefault('modelname', name)
                if (values.pop('permalink',None) 
                    or not g.get('permalink')):
                    values.setdefault('version', version)
                else:
                    values.setdefault('version',self.defaultversion)
            #transform components, specs into IDs
            if 'component' in values:
                values['componentid'] = values.pop('component').id
            if 'spec' in values:
                values['specid'] = values.pop('spec').id
            if 'match' in values:
                values['matchid'] = values.pop('match').id

        @self.bp.url_value_preprocessor
        def find_model(endpoint, values):
            query = None
            if 'modelid' in values:
                query = values.pop('modelid')
            elif 'modelname' in values:
                query={'name': values.pop('modelname')}
                version = values.pop('version',self.defaultversion)
                if version != self.defaultversion:
                    query['version'] = version
            if not query:
                abort(400, "Incomplete model specification")
            g.model = utils.getmodelordie(query,self.modeldb)
            if version == self.defaultversion:
                g.permalink = url_for(endpoint, permalink=True, **values) 


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
                return render_template("componentview.html", 
                                       component=component)
            else:
                return render_template("componentsoverview.html")


        @self.bp.route('/emissions/')
        def emissionsoverview():
            return render_template("emissionsoverview.html")

        @self.bp.route('/emission/<specid>')
        def emissionview(specid):
            spec = utils.getspecordie(g.model, specid)
            #find all simulation datasets associated to this spec
            datasets = []
            for comp in spec.appliedto:
                for simd in comp.getsimdata(rebuild=False, children=False):
                    if (simd.spec is spec 
                        or simd.spec in getattr(spec,'subspecs',[])):
                        for match in simd.matches:
                            if match.dataset:
                                datasets.append(match.dataset)
            return render_template('emissionview.html', spec=spec, 
                                   datasets=datasets)

        @self.bp.route('/simulations/')
        def simulationsoverview():
            return render_template("simulationsoverview.html")
            
        @self.bp.route('/queries/')
        def queriesoverview():
            #build a unique list of all queries
            queries = {}
            for request in g.model.assemblyroot.getsimdata():
                for match in request.matches:
                    try:
                        queries[str(match.query)].append(match)
                    except KeyError:
                        queries[str(match.query)] = [match]
            return render_template('queriesoverview.html',queries=queries)
         
        @self.bp.route('/dataset/<dataset>')
        def datasetview(dataset):
            detail = detail=self.simsdb.getdatasetdetails(dataset)
            return render_template("datasetview.html", dataset=dataset, 
                                   detail = detail)
                                   
        @self.bp.route('/simdatamatch/<matchid>')
        def simdatamatchview(matchid):
            match = utils.getsimdatamatchordie(g.model, matchid)
            #might not be able to generate a link to a subspec, so build here
            linkspec = match.request.spec
            if not hasattr(linkspec,'id') or linkspec.id not in g.model.specs:
                for spec in match.request.assemblyPath[-1].getspecs():
                    if hasattr(spec,'subspecs') and linkspec in spec.subspecs:
                        linkspec = spec
                        break
            return render_template("simdatamatchview.html", match=match,
                                   linkspec=linkspec)
            
        
        @self.bp.route('/billofmaterials')
        def billofmaterials():
            bomrows = bomfuncs.getbomrows()
            return render_template("billofmaterials.html", 
                                   bomrows=bomrows,
                                   bomcols=self.bomcols)
            
        #need to pass simsdb here because somehow it gets lost on repeat calls
        def streamdatatable(matches, groups, values, simsdb):
            """Stream exported data table so it doesn't all go into mem at once
            """
            #can't evaluate values if we don't have a simsdb
            values = values if simsdb else {}
            valitems = list(values.values())
            #send the header
            yield('\t'.join(chain(['ID'],
                                  ('G_'+g for g in groups),
                                  ('V_'+v for v in values)))
                  +'\n')
            #loop through matches
            for match in matches:
                if valitems:
                    evals = simsdb.evaluate(valitems, match)
                    for vlabel, val in values.items():
                        unit = self.values_units.get(vlabel,None)
                        if unit:
                            try:
                                evals[val] = evals[val].to(unit).m
                            except AttributeError: #not a Quantity...
                                pass
                yield('\t'.join(chain([match.id],
                                      (str(g(match)) for g in self.groups.values()),
                                      (str(evals[v]) for v in valitems)))
                      +'\n')
            
        @self.bp.route('/datatable')
        def datatable():
            """Return groups and values for all simdatamatches"""
            matches = sum((r.matches for r in g.model.getsimdata()),[])
            return Response(streamdatatable(matches, self.groups, self.values,
                                            self.simsdb), mimetype='text/plain')
