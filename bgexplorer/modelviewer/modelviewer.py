#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from itertools import chain
from flask import (Blueprint, render_template, request, abort, url_for, g, 
                   Response)
import threading
import zlib
import json

from bson import ObjectId

from .. import utils

from . import billofmaterials as bomfuncs
from ..modeldb import InMemoryCacher

class ModelViewer(object):
    """Blueprint for inspecting saved model definitions
    Args:
        app:  The bgexplorer Flask object
        modeldb: a ModelDB object. If None, will get from the Flask object
        simsdb:  a SimulationsDB object. If None, will get from the Flask object
        url_prefix (str): Where to mount this blueprint relative to root
        groups (dict): Grouping functions to evaluate for all simdatamatches
        goupsort (dict): Sorting function in the form of a list of expected 
                         values. Will be passed to javascript functions
        values (dict): Value functions to evaluate for all simdatamatches
    """
    defaultversion='HEAD'
    defaultgroups = {
        "Component": lambda match: [c.name for c in match.assemblyPath],
        "Material": lambda match: match.component.material,
        "Source": lambda match: match.spec.name,
        "Source Category": lambda match: match.spec.category,
    }

    joinkey = '___'

    def __init__(self, app=None, modeldb=None, simsdb=None,
                 cacher=InMemoryCacher(),
                 url_prefix='/explore', groups=None, groupsort=None,
                 values=None, values_units=None):
        self.app = app
        self._modeldb = modeldb
        self._simsdb = simsdb
        
        self.bp = Blueprint('modelviewer', __name__,
                            static_folder='static', 
                            template_folder='templates',
                            url_prefix='/<modelname>/<version>')
        
        self.bp.add_app_template_global(lambda : self, 'getmodelviewer')    
        self.set_url_processing()
        self.register_endpoints()
        
        if self.app:
            self.init_app(app, url_prefix)

            
        self.groups = groups or self.defaultgroups
        self.groupsort = groupsort or {}
        self.values = values or {}
        self.values_units = values_units or {}
        self._threads = {}
        self._cacher = cacher
        #### User Overrides ####
        self.bomcols = bomfuncs.getdefaultcols()
        
        #replace groupsort nested lists with joined strings
        for key,val in list(self.groupsort.items()):
            if isinstance(val,(list, tuple)):
                val = [self.joinkey.join(i) if isinstance(i,(list,tuple)) else i
                       for i in val]
                self.groupsort[key] = val
            
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
                g.permalink = url_for(endpoint, permalink=True, 
                                      **values) 
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

        @self.bp.route('/export')
        def export():
            """Present the model as a JSON document"""
            d = g.model.todict()
            #replace ObjectIds with strings
            if isinstance(d.get('_id'), ObjectId):
                d['_id'] = str(d['_id'])
            if isinstance(d.get('editDetails',{}).get('derivedFrom'), ObjectId):
               d['editDetails']['derivedFrom'] = str(d['editDetails']['derivedFrom'])
            return json.dumps(d)
         
    #need to pass simsdb because it goes out of context
    def streamdatatable(self, model, simsdb):
        """Stream exported data table so it doesn't all go into mem at once
        """
        #can't evaluate values if we don't have a simsdb
        values = self.values if simsdb else {}
        valitems = list(values.values())
        matches = model.simdatamatches.values()
        #send the header
        valheads = ['V_'+v+(' [%s]'%self.values_units[v] 
                            if v in self.values_units else '') 
                    for v in values]
        yield('\t'.join(chain(['ID'],
                              ('G_'+g for g in self.groups),
                              valheads))
              +'\n')
        #loop through matches
        for match in matches:
            if valitems:
                evals = simsdb.evaluate(valitems, match)
                for index, vlabel in enumerate(values):
                    unit = self.values_units.get(vlabel,None)
                    if unit:
                        try:
                            evals[index] = evals[index].to(unit).m
                        except AttributeError: #not a Quantity...
                            pass
            groupvals = (g(match) for g in self.groups.values())
            groupvals = (self.joinkey.join(g) 
                         if isinstance(g,(list,tuple)) else g
                         for g in groupvals)
            yield('\t'.join(chain([match.id],
                                  (str(g) for g in groupvals),
                                  ("{:.3g}".format(eval) for eval in evals)))
                  +'\n')
            
        

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
        simsdb = self.simsdb
        def cachedatatable():
            compressor = zlib.compressobj()
            res = b''.join(compressor.compress(s.encode('utf-8')) 
                           for s in self.streamdatatable(model,simsdb))
            res += compressor.flush()
            self._cacher.store(key, res)
            self._threads.pop(key) #is this a bad idea???
        
        thread = threading.Thread(target=cachedatatable,name=key)
        self._threads[key] = thread
        thread.start()
        return thread
        
    def get_datatable(self, model):
        """Return a Result object with the encoded or streamed datatable"""
        key = self.datatablekey(model)
        if not self._cacher:
            #no cache, so stream it directly, don't bother to zip it
            #should really be text/csv, but then browsersr won't let you see it
            return Response(self.streamdatatable(model,self.simsdb),
                            mimetype='text/plain')
        
        if not self._cacher.test(key):
            thread = self.build_datatable(model)
            if thread:
                thread.join() #wait until it's done
        res = self._cacher.get(key)
        if not res:
            abort(500,"Unable to generate datatable")
        return Response(res, headers={'Content-Type':'text/plain;charset=utf-8',
                                      'Content-Encoding':'deflate'})
        
        
    def get_componentsort(self, component):
        """Return an array component names in assembly order to be passed
        to the javascript analyzer for sorting component names
        """
        #TODO: cache this
        result = [component.name]
        for child in component.getcomponents(merge=False):
            result.extend(self.joinkey.join((component.name, s) )
                          for s in self.get_componentsort(child))
        return result

        
    def get_groupsort(self):
        res = dict(**self.groupsort)
        #todo: set up provided lists
        if 'Component' not in res:
            res['Component'] = self.get_componentsort(g.model.assemblyroot)
        return res
