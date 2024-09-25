import flask
from flask import Flask, render_template, Blueprint, json, abort
from flask_bootstrap import Bootstrap
from flask_basicauth import BasicAuth
import inspect
import os
import logging
import functools
from bson import ObjectId, json_util

from .modeleditor.modeleditor import ModelEditor
from .modelviewer.modelviewer import ModelViewer
from .simsviewer.simsviewer import SimsViewer
from .assaydb.assaydb import AssayDB
from .modeldb import ModelDB
from .utils import getobjectid
from .modeleditor.forms import NewModelForm
from .dbview import HitEffDbConfig, HitEffDB, HitEffDbView

from flask.json.tag import JSONTag


class TagObjectId(JSONTag):
    key = '$oid'

    def check(self, value):
        return isinstance(value, ObjectId)

    def to_json(self, value):
        return str(value)

    def to_python(self, value):
        return ObjectId(value)


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        return json_util.default(o)


def decode_object_hook(obj, base=None):
    obj = json_util.object_hook(obj)
    return obj if base is None else base(obj)


class CustomJSONDecoder(json.JSONDecoder):
    def __init__(self, **kwargs):
        baseoh = kwargs.pop('object_hook', None)
        oh = functools.partial(decode_object_hook, base=baseoh)
        super().__init__(object_hook=oh, **kwargs)


class BgExplorer(Flask):
    """ Shallow wrapper around Flask application, providing mechanism
    to register multiple simulation databases.
    """

    def __init__(self, config_filename=None, instance_path=None, simviews=None):
        """ Constructor
        Args:
            config_filename (str): filename to use for configuration. If
                                   instance_path is None, will be in
                                   bgexplorer's local directory
            instance_path (str): location to look for config files
            simviews (dict): optional dictionary of 'name':SimDbView to define
                             all the simulation views

        BgExplorer uses some special keys in configuration:
            SIMDBVIEWS_DEFAULT (str): the default SimDbView to use if not specified.
                If not provided, it will be set to the first registered view
        """
        if instance_path is None:
            instance_path = os.getcwd()
            #caller = inspect.stack()[1][1]
            #instance_path = os.path.dirname(os.path.abspath(caller))

        super().__init__('bgexplorer', instance_path=instance_path,
                         instance_relative_config=bool(instance_path))

        app = self
        app.config.from_object('bgexplorer.config_default')
        # test for Docker config files
        try:
            app.config.from_pyfile('/bgexplorer_app_config')
        except FileNotFoundError:
            pass
        try:
            app.config.from_pyfile('/run/secrets/flask_secret_key')
        except FileNotFoundError:
            pass
        # override with user-supplied config
        if config_filename:
            print("Loading configuration from file", config_filename)
            app.config.from_pyfile(config_filename)

        # define simviews
        self.simviews = simviews or {}
        if app.config.get('SIMDB_BACKENDS'):
            HitEffDB.connect(app)
        for viewname in app.config.get('SIMDB_BACKENDS', []):
            if viewname in self.simviews:
                continue
            # see if it's in the DB already
            try:
                dbconf = HitEffDbConfig.objects.get(name=viewname)
            except (HitEffDbConfig.MultipleObjectsReturned,
                    HitEffDbConfig.DoesNotExist):
                dbconf = HitEffDbConfig(name=viewname)
            self.addsimview(viewname, HitEffDbView(HitEffDB(dbconf)))

        # override json encode/decode to handle object IDs
        app.json_encoder = CustomJSONEncoder
        app.json_decoder = CustomJSONDecoder
        app.session_interface.serializer.register(TagObjectId, index=0)

        # set up logging
        logformat = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        loglevel = app.config.get('LOGLEVEL', logging.WARNING)
        if app.debug:
            loglevel = logging.DEBUG

        logfile = app.config.get('LOGFILE')
        #logging.basicConfig(format=logformat, level=level)
        if logfile:
            app.logger.removeHandler(flask.logging.default_handler)
            from logging.handlers import RotatingFileHandler

            file_handler = RotatingFileHandler(logfile, maxBytes=1024*1024*100,
                                               backupCount=20)
            file_handler.setLevel(loglevel)
            formatter = logging.Formatter(logformat)
            file_handler.setFormatter(formatter)
            # app.logger.addHandler(file_handler)
            logging.getLogger().addHandler(file_handler)
            logging.getLogger().setLevel(loglevel)
        else:
            logging.basicConfig(format=logformat, level=loglevel)
        app.logger.info("Log level is %s", loglevel)

        logging.getLogger('matplotlib').setLevel(logging.WARNING)

        # set up extensions
        BasicAuth(app)
        Bootstrap(app)
        self.modeldb = ModelDB(app=app)
        # register custom templates first so they can override
        app.register_blueprint(Blueprint('custom', instance_path,
                                         static_folder='static',
                                         template_folder='templates',
                                         url_prefix='/custom'))
        self.modeleditor = ModelEditor(app=app, modeldb=self.modeldb)
        self.modelviewer = ModelViewer(app=app, modeldb=self.modeldb)
        self.simsviewer = SimsViewer(app=app)
        self.assaydb = AssayDB(app=app)

        # set up some views
        app.add_template_filter(getobjectid, 'id')

        @app.route('/')
        def index():
            models = app.modeldb.get_models_list(includetemp=True,
                                                 mostrecentonly=False)
            return render_template("listmodels.html", models=models,
                                   newmodelform=NewModelForm())

    def addsimview(self, name, simview):
        """ Register a new simulation database view interface
        Args:
            name (str): unique name for this database interface
            simview (SimDbView): Object specifying the interface

        This should be called AFTER application configuration is set to enable
        cloning
        """
        # dont' overrite previously registered view
        if name in self.simviews:
            raise KeyError(f"SimDbView {name} is already registered")
        self.simviews[name] = simview

        # if we don't have a default view yet, make it this one
        self.config.setdefault('SIMDBVIEW_DEFAULT', name)

    def getsimview(self, name=None):
        if not name:
            try:
                name = self.config['SIMDBVIEW_DEFAULT']
            except KeyError:
                abort(404, 'SimDbView name not provided and no default set')
        if name not in self.simviews:
            # try to get from db-configured HitEffDbConfigs
            try:
                dbconf = HitEffDbConfig.objects.get(name=name)
            except (HitEffDbConfig.MultipleObjectsReturned,
                    HitEffDbConfig.DoesNotExist):
                abort(404, f"No SimsDbView backend with name {name}")
            # do we want to save this in simviews?
            return HitEffDbView(dbconf)
        return self.simviews[name]

    def getsimviewname(self, simsdbview):
        """ Find the name associated with this view """
        for name, view in self.simviews.items():
            if view is simsdbview:
                return name
        return None

    def getdefaultsimviewname(self):
        return self.config.get('SIMDBVIEW_DEFAULT')


def create_app(*args, **kwargs):
    """ Simple wrapper to make app easier to find for wsgi server testing """
    return BgExplorer(*args, **kwargs)

def main():
    import sys
    from glob import glob
    app = create_app(sys.argv[1] if len(sys.argv)>1 else None,
                     instance_path=os.getcwd())
    app.config.update({'DEBUG':True,'TESTING':True,
                       'TEMPLATES_AUTO_RELOAD':True,
                       #'EXPLAIN_TEMPLATE_LOADING':True,
                      })
    app.secret_key = "not very secret is it?"
    #force template reloading, even though it shouldn't be necessary
    templates = glob("bgexplorer/templates/*.html")
    templates.extend(glob("bgexplorer/*/templates/*.html"))
    app.run(host='0.0.0.0', port=app.config.get('SERVER_PORT'),
            extra_files=templates)

if __name__ == '__main__':
    main()
