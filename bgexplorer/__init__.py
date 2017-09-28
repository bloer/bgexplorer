from flask import Flask, render_template
from flask_bootstrap import Bootstrap

from .modeleditor.modeleditor import ModelEditor
from .modeldb import ModelDB


def create_app(config_filename=None):
    app = Flask(__name__)
    if config_filename:
        app.config.from_pyfile(config_filename)
        
    Bootstrap(app)
    modeldb = ModelDB(app=app)
    modeleditor = ModelEditor(app=app, modeldb=modeldb)

    @app.route('/')
    def index():
        return render_template("listmodels.html",
                               models=modeldb.get_models_list())

    return app

