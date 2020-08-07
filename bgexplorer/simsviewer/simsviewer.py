from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from flask import (Blueprint, render_template, render_template_string,
                   request, abort, url_for, g, json, flash, redirect,
                   Response, get_flashed_messages, current_app)

from .. import utils
import gzip
import zipfile
import tarfile
#import json


def findsimmatches(dataset, model=None):
    """find all simdatamatch objects associated with the given dataset"""
    res = []
    model = g.get('model', model)
    if not model:
        return res
    #make sure we're not working with a full dataset object
    try:
        dataset = dataset.get('_id')
    except AttributeError:
        pass

    for match in model.getsimdata():
        if match.dataset == dataset:
            res.append(match)
        else:
            try:
                if dataset in match.dataset:
                    res.append(match)
            except TypeError:
                pass
    return res


class SimsViewer(object):
    """Blueprint for searching and inspecting simulation data
    Args:
        app: the bgexplorer Flask object
        url_prefix (str): Where to mount this blueprint relative to root
        detailtemplate: path to template file for detailed simulation view
        enableupload (bool): if True, allow uploading new entries
        uploadsummary (func): generate a summary projection from uploaded
                              (json-generated) documents
    """
    def __init__(self, app=None, url_prefix='/simulations',
                 detailtemplate=None,
                 enableupload=True, uploadsummary=None):
        self.app = app
        self.enable_upload = enableupload
        self.uploadsummary = uploadsummary

        self.bp = Blueprint('simsviewer', __name__,
                            static_folder='static',
                            template_folder='templates')
        self.bp.add_app_template_global(lambda : self, 'getsimsviewer')
        self.bp.add_app_template_global(findsimmatches, 'findsimmatches')
        self.bp.add_app_template_global(json.dumps, 'json_dumps')

        #handle 'query' requests for non strings
        @self.bp.url_defaults
        def url_defaults(endpoint, values):
            query=values.get('query', None)
            if query and not isinstance(query, str):
                values['query'] = json.dumps(query)

        @self.bp.before_request
        def preprocess():
            if 'query' in request.args:
                try:
                    args = request.args.copy()
                    args['query'] = json.loads(args['query'])
                    request.args = args
                except (KeyError, json._json.JSONDecodeError):
                    pass

        self.register_endpoints()
        if self.app:
            self.init_app(app, url_prefix)

    def init_app(self, app, url_prefix=''):
        """Register ourselves with the app"""
        app.register_blueprint(self.bp,
                               url_prefix=url_prefix)
        app.extensions['SimulationsViewer'] = self
        key = "ENABLE_SIMULATION_UPLOADS"
        self.enable_upload = app.config.setdefault(key, self.enable_upload)


    @property
    def simsdb(self):
        return g.simsdbview.simsdb

    def getcolnames(self, sims):
        """ Get the column names to display in summary table """
        columns = []
        try:
            columns = g.simsdbview.summarycolumns
        except AttributeError:
            pass
        if sims and not columns:
            #non-underscore keys with string or number values
            for key, val in sims[0].items():
                if (not key.startswith('_')
                    and key != 'id'
                    and isinstance(val,(str,int,float))):
                    columns.append(key)
        return columns

    def register_endpoints(self):
        """Attach the model if requested"""
        @self.bp.url_value_preprocessor
        def find_model(endpoint, values):
            if 'modelid' in request.args:
                g.model = utils.getmodelordie(request.args['modelid'])
                values.setdefault('dbname', g.model.simsdb)
            if 'dbname' in values:
                g.simsdbview = utils.get_simsdbview(name=values.pop('dbname'))

        """ make sure we have a simsdb """
        @self.bp.url_defaults
        def addsimsdbview(endpoint, values):
            model = values.pop('model', None) or g.get('model', None)
            if model:
                values['modelid'] = model.id
                dbname = model.simsdb
                if not dbname:
                    dbname = current_app.getdefaultsimviewname()
                values.setdefault('dbname', dbname)

            simsdbview = values.pop('simsdbview', None) or g.get('simsdbview', None)
            if simsdbview:
                values['dbname'] = current_app.getsimviewname(simsdbview)



        """Define the view functions here"""
        @self.bp.route('/')
        def index():
            dbnames = list(current_app.simviews.keys())
            if len(dbnames) == 1:
                return redirect(url_for('.overview', dbname=dbnames[0]))
            return render_template('listdbs.html', dbnames=dbnames)

        @self.bp.route('/<dbname>/')
        def overview():
            query = request.args.get('query',None)
            try:
                projection = g.simsdbview.summarypro
                sims = list(self.simsdb.runquery(query, projection=projection))
            except Exception as e:
                abort(400, "Invalid query specifier")
            columns = self.getcolnames(sims)
            return render_template('simoverview.html', sims=sims, query=query,
                                   colnames=columns)

        @self.bp.route('/<dbname>/dataset/<dataset>')
        def detailview(dataset):
            detail = self.simsdb.getdatasetdetails(dataset)
            matches = findsimmatches(dataset)
            return render_template('datasetview.html',dataset=dataset,
                                   detail=detail)


        @self.bp.route('/<dbname>/dataset/<dataset>/raw')
        def rawview(dataset):
            """Export the dataset as raw JSON"""
            detail = self.simsdb.getdatasetdetails(dataset)
            return json.jsonify(detail)

        if not self.enable_upload:
            return

        @self.bp.route('/<dbname>/upload', methods=('GET','POST'))
        def upload():
            """ Upload new JSON-formatted entries """
            if request.method == 'POST':
                flist = request.files.getlist('fupload')
                newentries = sum((self.parseupload(f) for f in flist), [])
                if newentries:
                    sims = newentries
                    if self.uploadsummary:
                        sims = list(map(self.uploadsummary, newentries))
                    colnames = self.getcolnames(sims)
                    return render_template('simoverview.html', sims=sims,
                                           colnames=colnames, temp=True,
                                           fullentries=newentries)
                else:
                    flash("No valid entries in uploaded files",'error')
            return render_template('uploadsimdata.html')

        @self.bp.route('/<dbname>/confirmupload', methods=('POST',))
        def confirmupload():
            """ Confirm uploads with form """
            confirmed = []
            for key, val in request.form.items():
                if key.startswith('simdata'):
                    num = key[7:]
                    confirm = request.form.get('confirm'+num,'off') == 'on'
                    if confirm:
                        confirmed.append(val)
            numinserted = 0
            for entry in confirmed:
                try:
                    self.simsdb.addentry(entry, fmt='json')
                    numinserted += 1
                except Exception as e:
                    flash("Database error occurred: %s"%e, 'error')
            flash("%d sim data entries successfully added"%numinserted,
                  'success' if numinserted > 0 else 'error')
            return redirect(url_for('.overview'))

    def parseupload(self, afile):
        files = [afile]
        # see if it's a zip or gzip archive
        try:
            tf = tarfile.open(fileobj=afile)
            files = [tf.extractfile(name) for name in tf.getnames()]
            for f,name in zip(files, tf.getnames()):
                f.filename = name
        except tarfile.TarError:
            afile.seek(0)
            pass
        try:
            zf = zipfile.ZipFile(afile)
            files = [_ZipExtSeekable(zf, name) for name in zf.namelist()]
        except zipfile.BadZipFile:
            afile.seek(0)
            pass

        def _load(jfile):
            with gzip.open(jfile) as decomp:
                result = None
                try:
                    result = json.load(decomp)
                except OSError:
                    jfile.seek(0)
                    result = json.load(jfile)
                except (json._json.JSONDecodeError) as e:
                    flash("Error decoding JSON: %s"%e, 'error')
            try:
                result['_filename'] = getattr(jfile, 'filename', jfile.name)
            except (AttributeError, TypeError):
                pass
            return result
        return list(filter(lambda x: x is not None, map(_load, files)))


class _ZipExtSeekable(object):
    """ Wrap a 3.6 ZipExtFile to emulate seek(0) """
    def __init__(self, zipfile, name):
        self.zipfile = zipfile
        self.name = name
        self.seek(0)

    def seek(self, to, whence=None):
        # only seek(0) is sensible
        self.ext = self.zipfile.open(self.name)

    def seekable(self):
        return True

    def __getattr__(self, attr):
        return getattr(self.ext, attr)
