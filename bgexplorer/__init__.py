from flask import Flask, render_template
from flask_bootstrap import Bootstrap
import itertools

from .modeleditor.modeleditor import ModelEditor
from .modelviewer.modelviewer import ModelViewer
from .modeldb import ModelDB

def create_app(config_filename=None, simsdb=None, instance_path=None,
               groups=None, values=None, values_units=None):
    """Create the Flask application and bind blueprints. 
    
    Args:
        config_filename (str): filename to use for configuration. If 
                               instance_path is None, will be in bgexplorer's 
                               local directory
        simsdb: A SimulationsDB concrete instance. Can be bound to app 
                later by `simsdb.init_app(app)`
        instance_path (str): location to look for config files. 
        groups: dictionary of grouping functions to cache on all simdatamtches
        values: dictionary of value functions to cache on all simdatamatches
        values_units: optional dictionary of units to render values in in the 
                      cached datatable
    
    TODO: have instance_path default to PWD? 
    """
    app = Flask('bgexplorer', instance_path=instance_path,
                instance_relative_config=bool(instance_path))
    if config_filename:
        app.config.from_pyfile(config_filename)
        
    Bootstrap(app)
    modeldb = ModelDB(app=app)
    modeleditor = ModelEditor(app=app, modeldb=modeldb)
    modelviewer = ModelViewer(app=app, modeldb=modeldb, simsdb=simsdb,
                              groups=groups, values=values, 
                              values_units=values_units)
    if simsdb:
        simsdb.init_app(app)

    @app.route('/')
    def index():
        models = modeldb.get_models_list(mostrecentonly=False)
        mgroups = list((n,list(g)) for n, g in 
                        itertools.groupby(models, lambda m: m['name']))
        return render_template("listmodels.html", models=models, 
                               modelgroups=mgroups)

    return app


