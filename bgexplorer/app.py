from flask import Flask, render_template, Blueprint
from flask_bootstrap import Bootstrap
from flask_basicauth import BasicAuth
import itertools
import inspect
import os
import logging

from .modeleditor.modeleditor import ModelEditor
from .modelviewer.modelviewer import ModelViewer
from .simsviewer.simsviewer import SimsViewer
from .modeldb import ModelDB
from .bgmodelbuilder.common import units as ureg
from .utils import getobjectid

def create_app(config_filename=None, simsdb=None, instance_path=None,
               groups=None, groupsort=None, values=None, values_units=None):
    """Create the Flask application and bind blueprints. 
    
    Args:
        config_filename (str): filename to use for configuration. If 
                               instance_path is None, will be in bgexplorer's 
                               local directory
        simsdb: A SimulationsDB concrete instance. Can be bound to app 
                later by `simsdb.init_app(app)`
        instance_path (str): location to look for config files. 
        groups: dictionary of grouping functions to cache on all simdatamtches
        groupsort: dictionary of lists to sort group values
        values: dictionary of value functions to cache on all simdatamatches
        values_units: optional dictionary of units to render values in in the 
                      cached datatable
    
    TODO: have instance_path default to PWD? 
    """
    #if instance_path is not explicitly defined, use the caller's path
    if instance_path is None:
        instance_path = os.path.dirname(os.path.abspath(inspect.stack()[1][1]))

    app = Flask('bgexplorer', instance_path=instance_path,
                instance_relative_config=bool(instance_path))
    if config_filename:
        app.config.from_pyfile(config_filename)
    BasicAuth(app)

    #set up logging
    logformat = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    if app.debug:
        logging.basicConfig(format=logformat, level=logging.DEBUG)
    else:
        logfile = app.config.get('LOGFILE')
        if logfile:
            from logging.handlers import RotatingFileHandler
            level = app.config.get('LOGLEVEL',logging.WARNING)
            logging.basicConfig(filename=logfile, format=logformat, level=level)

            file_handler = RotatingFileHandler(logfile, maxBytes=1024*1024*100,
                                               backupCount=20)
            file_handler.setLevel(app.config.get('LOGLEVEL',logging.DEBUG))
            formatter = logging.Formatter(format)
            file_handler.setFormatter(formatter)
            app.logger.addHandler(file_handler)
    
        
    Bootstrap(app)
    modeldb = ModelDB(app=app)
    #register custom templates first so they can override
    app.register_blueprint(Blueprint('custom', instance_path, 
                                     static_folder='static', 
                                     template_folder='templates', 
                                     url_prefix='/custom'))
    modeleditor = ModelEditor(app=app, modeldb=modeldb)
    modelviewer = ModelViewer(app=app, modeldb=modeldb, simsdb=simsdb,
                              groups=groups, groupsort=groupsort,values=values, 
                              values_units=values_units)
    simsviewer = SimsViewer(app=app, simsdb=simsdb)
    if simsdb:
        simsdb.init_app(app)
        
    app.add_template_filter(getobjectid, 'id')
        
    @app.route('/')
    def index():
        models = modeldb.get_models_list(includetemp=True, mostrecentonly=False)
        return render_template("listmodels.html", models=models)

    return app


