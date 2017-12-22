from flask import Flask, render_template
from flask_bootstrap import Bootstrap
import itertools

from .modeleditor.modeleditor import ModelEditor
from .modelviewer.modelviewer import ModelViewer
from .modeldb import ModelDB

def create_app(config_filename=None, simsdb=None, instance_path=None):
    """Create the Flask application and bind blueprints. 
    
    TODO: handle config better, and move non-fixed things to an example
    """
    app = Flask('bgexplorer', instance_path=instance_path,
                instance_relative_config=bool(instance_path))
    if config_filename:
        app.config.from_pyfile(config_filename)
        
    Bootstrap(app)
    modeldb = ModelDB(app=app)
    modeleditor = ModelEditor(app=app, modeldb=modeldb)
    modelviewer = ModelViewer(app=app, modeldb=modeldb, simsdb=simsdb)
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


