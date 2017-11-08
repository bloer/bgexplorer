from flask import Flask, render_template
from flask_bootstrap import Bootstrap

from .modeleditor.modeleditor import ModelEditor
from .modeldb import ModelDB
from .bgmodelbuilder.simulationsdb.mongosimsdb import MongoSimsDB

def create_app(config_filename=None):
    """Create the Flask application and bind blueprints. 
    
    TODO: handle config better, and move non-fixed things to an example
    """
    app = Flask(__name__)
    if config_filename:
        app.config.from_pyfile(config_filename)
        
    Bootstrap(app)
    modeldb = ModelDB(app=app)
    modeleditor = ModelEditor(app=app, modeldb=modeldb)
    simsdb = MongoSimsDB(modeldb._database['simdata'], app=app)

    @app.route('/')
    def index():
        return render_template("listmodels.html",
                               models=modeldb.get_models_list())

    return app


