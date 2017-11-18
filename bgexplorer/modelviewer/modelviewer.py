#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from flask import Blueprint, render_template, request, abort, url_for, g

from .. import utils

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
                

        @self.bp.url_value_preprocessor
        def find_model(endpoint, values):
            print(values)
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
        @self.bp.route('/component/<compid>') #should be uuid type?
        def componentview(compid=None):
            if compid:
                component = utils.getcomponentordie(g.model, compid)
            else:
                component = g.model.assemblyroot
            return render_template("componentview.html", component=component)

        @self.bp.route('/emissions/')
        def emissionsoverview():
            return render_template("emissionsoverview.html")

        @self.bp.route('/simulations/')
        def simulationsoverview():
            return render_template("simulationsoverview.html")
            
        
    
