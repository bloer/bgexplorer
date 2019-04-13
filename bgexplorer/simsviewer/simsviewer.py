from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from flask import (Blueprint, render_template, render_template_string,
                   request, abort, url_for, g, 
                   Response)
from .. import utils
import json


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
        simsdb: a SimulationsDB object. If None, will get from the Flask object
        url_prefix (str): Where to mount this blueprint relative to root
        summarypro: a projection operator to generate flat summary tables
        summarycolumns (list): list of column names for summary page
        detailtemplate: path to template file for detailed simulation view
    """
    def __init__(self, app=None, simsdb=None, url_prefix='/simulations',
                 summarypro=None, summarycolumns=None, detailtemplate=None):
        self.app = app
        self._simsdb = simsdb
        self.summarypro = summarypro
        self.summarycolumns = summarycolumns

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
                except (KeyError, json.JSONDecodeError):
                    pass
        
        self.register_endpoints()
        if self.app:
            self.init_app(app, url_prefix)

    def init_app(self, app, url_prefix=''):
        """Register ourselves with the app"""
        app.register_blueprint(self.bp, 
                               url_prefix=url_prefix)
        app.extensions['SimulationsViewer'] = self
        key = 'SIMULATIONSVIEWER_SUMMARY_PROJECTION'
        self.summarypro = app.config.setdefault(key, self.summarypro)
        key = 'SIMULATIONSVIEWER_SUMMARY_COLUMNS'
        self.summarycolumns = app.config.setdefault(key, self.summarycolumns)
        

    @property
    def simsdb(self):
        return self._simsdb or utils.get_simsdb()
    
    def register_endpoints(self):
        """Attach the model if requested"""
        @self.bp.url_value_preprocessor
        def find_model(endpoint, values):
            if 'modelid' in request.args:
                g.model = utils.getmodelordie(request.args['modelid'])


        """Define the view functions here"""
        @self.bp.route('/')
        def overview():
            query = request.args.get('query',None)
            sims = list(self.simsdb.runquery(query, 
                                             projection=self.summarypro))
            columns = self.summarycolumns or []
            if sims and not columns:
                #non-underscore keys with string or number values
                for key, val in sims[0].items():
                    if (not key.startswith('_') 
                        and key != 'id'
                        and isinstance(val,(str,int,float))):
                        columns.append(key)
            return render_template('simoverview.html', sims=sims, query=query,
                                   colnames=columns)
        
        @self.bp.route('/dataset/<dataset>')
        def detailview(dataset):
            detail = self.simsdb.getdatasetdetails(dataset)
            matches = findsimmatches(dataset)
            return render_template('datasetview.html',dataset=dataset,
                                   detail=detail)
            

        @self.bp.route('/dataset/<dataset>/raw')
        def rawview(dataset):
            """Export the dataset as raw JSON"""
            detail = self.simsdb.getdatasetdetails(dataset)
            return Response(json.dumps(detail), mimetype='application/json')
