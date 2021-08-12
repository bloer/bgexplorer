from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from flask import (Blueprint, render_template,
                   request, abort, url_for, g, json, redirect, current_app)

from .. import utils
import io


def findsimmatches(dataset, model=None):
    """find all simdatamatch objects associated with the given dataset"""
    res = []
    model = g.get('model', model)
    if not model:
        return res
    # make sure we're not working with a full dataset object
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
        self.bp.add_app_template_global(lambda: self, 'getsimsviewer')
        self.bp.add_app_template_global(findsimmatches, 'findsimmatches')
        self.bp.add_app_template_global(json.dumps, 'json_dumps')

        # handle 'query' requests for non strings
        @self.bp.url_defaults
        def url_defaults(endpoint, values):
            query = values.get('query', None)
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
            # non-underscore keys with string or number values
            for key, val in sims[0].items():
                if (not key.startswith('_')
                    and key != 'id'
                        and isinstance(val, (str, int, float))):
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
                g.dbname = values.pop('dbname')
                g.simsdbview = utils.get_simsdbview(name=g.dbname)

        """ make sure we have a simsdb """
        @self.bp.url_defaults
        def addsimsdbview(endpoint, values):
            model = values.pop('model', None) or g.get('model', None)
            if model:
                #values['modelid'] = model.id
                dbname = model.simsdb
                if not dbname:
                    dbname = current_app.getdefaultsimviewname()
                values.setdefault('dbname', dbname)

            simsdbview = values.pop(
                'simsdbview', None) or g.get('simsdbview', None)
            if simsdbview and 'dbname' not in values:
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
            query = request.args.get('query', None)
            try:
                projection = g.simsdbview.summarypro
                sims = list(self.simsdb.runquery(query, projection=projection))
            except Exception:
                abort(400, "Invalid query specifier")
            columns = self.getcolnames(sims)
            return render_template('simoverview.html', sims=sims, query=query,
                                   colnames=columns)

        @self.bp.route('/<dbname>/dataset/<dataset>')
        def detailview(dataset):
            detail = self.simsdb.getdatasetdetails(dataset)
            matches = findsimmatches(dataset)
            return render_template('datasetview.html', dataset=dataset,
                                   detail=detail, matches=matches)

        @self.bp.route('/<dbname>/dataset/<dataset>/raw')
        def rawview(dataset):
            """Export the dataset as raw JSON"""
            detail = self.simsdb.getdatasetdetails(dataset)
            return json.jsonify(detail)

        if not self.enable_upload:
            return

        @self.bp.route('/<dbname>/api/upload', methods=('POST',))
        def api_upload():
            """ Upload files to be inserted, return JSON response """
            files = request.files.getlist('fupload')
            if request.is_json:
                print(request.data, request.json)
                fakefile = io.BytesIO(request.data)
                fakefile.filename = 'JSON'
                files = [fakefile]
            try:
                result = g.simsdbview.handle_uploads(files)
            except NotImplementedError:
                abort(501, "Uploads are not implemented for this database")
            except BaseException as e:
                err = f"{type(e).__name__}: {str(e)}"
                result = dict(entries={}, errors={None: err})
            return result

        @self.bp.route('/<dbname>/upload', methods=('GET', 'POST'))
        def upload():
            """ Upload new JSON-formatted entries """
            result = None
            if request.method == 'POST':
                result = api_upload()
            return render_template('uploadsimdata.html', result=result)
