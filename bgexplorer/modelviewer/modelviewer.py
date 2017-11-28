#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from flask import Blueprint, render_template, request, abort, url_for, g
from collections import namedtuple
from .. import utils


BOMRow = namedtuple('BOMRow',('outline','path','component',
                              'weight','totalweight'))

def getbomrows(row, includeself=False, form="%02d"):
    """Recursive function to generate list of bomrows
    """
    myrows = [row] if includeself else []
    parent = row.component
    if hasattr(parent,'getcomponents'):
        form = "%02d" if len(parent.components)>10 else "%d"
        for index, cw in enumerate(parent.getcomponents(deep=False, 
                                                        withweight=True)):
            child, weight = cw
            outlineprefix = row.outline+'.' if row.outline else ''
            childrow = BOMRow(outline=("%s"+form)%(outlineprefix,index+1),
                              path=row.path+(child,),
                              component=child,
                              weight=weight,
                              totalweight=row.totalweight*weight)
            myrows.extend(getbomrows(childrow, includeself=True, form=form))
    return myrows
                              

class ModelViewer(object):
    """Blueprint for inspecting saved model definitions
    Args:
        app:  The bgexplorer Flask object
        modeldb: a ModelDB object. If None, will get from the Flask object
        simsdb:  a SimulationsDB object. If None, will get from the Flask object
        url_prefix (str): Where to mount this blueprint relative to root
    """
    defaultversion='HEAD'
    
    def __init__(self, app=None, modeldb=None, simsdb=None,
                 url_prefix='/explore'):
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
            #build up the list of rows from paths
            root = g.model.assemblyroot
            rows = getbomrows(BOMRow(outline='',
                                     path=(root,),
                                     component=root,
                                     weight=1,
                                     totalweight=1),
                              includeself=False,
                              form="%02d" if len(root.components)>10 else "%d")
            
            return render_template("billofmaterials.html", bomrows=rows)
