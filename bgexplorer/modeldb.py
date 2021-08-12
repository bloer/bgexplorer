# python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import pymongo
import bson
from datetime import datetime
from collections import OrderedDict, deque
from bgmodelbuilder.bgmodel import BgModel
from .utils import getobjectid
from .modelviewer.evaldata import genevalcache
import logging
log = logging.getLogger(__name__)


class InMemoryCacher(object):
    def __init__(self, maxentries=3):
        """Simple cache of most recently assembled models from the database.
        If new models are cached the oldest are removed first
        """
        self.maxentries = 3
        self.empty()

    def store(self, key, val):
        if key in self.registry:
            return key
        self.registry[key] = val
        self.byage.appendleft(key)
        if len(self.byage) > self.maxentries:
            self.expire()
        return key

    def get(self, key):
        # move this key to the top of the age queue
        if key in self.byage and self.byage.index(key) != 0:
            self.byage.remove(key)
            self.byage.appendleft(key)
        return self.registry.get(key, None)

    def test(self, key):
        return key in self.registry

    def expire(self, key=None):
        if not key:
            key = self.byage.pop()
        else:
            try:
                self.byage.remove(key)
            except ValueError:
                pass
        try:
            del self.registry[key]
        except KeyError:
            pass

    def empty(self):
        self.byage = deque([])
        self.registry = {}


class ModelDB(object):

    _default_uri = 'mongodb://localhost/modeldb'

    """Helper class to load/save BgModel objects to a (pymongo) database
    Args:
       dburi (str): a pymongo database URI connection string
       collection (str): the model collection as a string
       cacher: An object implementing store, get, and expire methods, to
               cache the most recently assembled model
    """

    def __init__(self, dburi=None, collection='bgmodels',
                 cacher=InMemoryCacher(), app=None):
        self._collectionName = collection
        self._client = None
        self._database = None
        self._collection = None
        self._cacher = cacher

        if dburi:
            self.connect(dburi)
        elif app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize from configuration parameters in a Flask app"""
        dburi = app.config.setdefault('MODELDB_URI',
                                      self._default_uri)
        self._collectionName = app.config.setdefault('MODELDB_COLLECTION',
                                                     'bgmodels')
        self.connect(dburi)
        app.extensions['ModelDB'] = self

    def connect(self, dburi=None, makecache=True):
        """Connect to the server and database identified by dburi"""
        if not dburi:
            dburi = self._default_uri
        log.info("Connecting to mongodb server at %s", dburi)

        self._client = pymongo.MongoClient(dburi)
        try:
            self._database = self._client.get_default_database()
        except pymongo.errors.ConfigurationError:
            log.warning("Database not provided in URI, connecting to 'test'")
            self._database = self._client.get_database('test')
        self._collection = self._database.get_collection(self._collectionName)
        # make sure the collection is properly indexed
        partialFilter = {'__modeldb_meta.temporary': False}
        self._collection.create_index((('name', pymongo.ASCENDING),
                                       ('version', pymongo.DESCENDING)),
                                      name='name_version',
                                      unique=True,
                                      partialFilterExpression=partialFilter)

        if makecache:
            cachecol = self._collection['evalcache']
            cachecol.create_index((('modelid', pymongo.ASCENDING),
                                   ('componentid', pymongo.ASCENDING),
                                   ('specid', pymongo.ASCENDING),
                                   ('matchid', pymongo.ASCENDING),
                                   ('dataname', pymongo.ASCENDING),
                                   ('fmt', pymongo.ASCENDING)),
                                  unique=True)

    def getevalcache(self):
        """ Get the collection used for evaluated data cache """
        return self._collection['evalcache']

    def clearevalcache(self, modelid):
        if modelid is not None:
            log.warning("Clearing evaluated data cache for model %s", modelid)
            self._collection['evalcache'].delete_many(dict(modelid=modelid))

    def testconnection(self):
        """Make sure we're connected to the database, otherwise raise exception
        """
        if not self._collection:
            self.connect()
            #raise RuntimeError("No active database connection")

    def makequery(self, query):
        """Accept queries in the form of raw IDs, which may be the string form
        of ObjectIDs. Convert `query` into a good form understandable to mongo
        """
        if not isinstance(query, dict):
            query = dict(_id=query)
        if '_id' in query:
            try:
                query['_id'] = bson.ObjectId(query['_id'])
            except bson.errors.InvalidId:  # id is not an ObjectId string
                pass
        else:
            # can only get temporary models by direct ID query
            # query.setdefault('__modeldb_meta.temporary',False)
            pass

        return query

    def get_raw_model(self, query, projection=None, withmeta=False):
        """Get the raw dict object for a model stored in the db
        Args:
            query(str or dict): pymongo query object. Should generally be a str
                or ObjectId corresponding to the model's ID or a dict with
                'name' and 'version' keys
            projection (dict): pymongo projection doc
            withmeta (bool):  If true, include the __modeldb_meta subdocument.
        """
        self.testconnection()
        # convert id query to ObjectId if it is a plain string
        query = self.makequery(query)
        # we need to get metadata every time
        projection = projection or {}
        if projection:
            if '__modeldb_meta' in projection:
                withmeta = projection['__modeldb_meta']
            projection['__modeldb_meta'] = True
        sort = None
        if '_id' not in query:
            sort = [('_id', pymongo.DESCENDING)]
            # if query only by name, don't look at temp models
            if 'name' in query and 'version' not in query:
                query['__modeldb_meta.temporary'] = False
        result = self._collection.find_one(query, projection or None,
                                           sort=sort)
        if not result:
            return None

        # see if we need to decode special key names
        encodedkeys = result.get('__modeldb_meta', {}).get('encodedkeys', [])
        if encodedkeys:
            self.decodebson(result, encodedkeys)
        if not withmeta:
            result.pop('__modeldb_meta', None)

        # change '_id' to 'id'
        return result

    def is_model_temp(self, modelid):
        """Is the model with id modelid temporary? Only temporary models
        are writeable!
        """
        # only non-temp models are cached, so if it's in cache, it's not temp
        if self._cacher.test(modelid):
            return False
        # not in cache, so need to check
        model = self.get_raw_model(modelid, {'__modeldb_meta': True})
        # todo: should we just return false here?
        if not model:
            raise KeyError("No model with ID ", modelid)
        return model['__modeldb_meta']['temporary']

    def get_model_history(self, modelid):
        """Helper function to get the editDetails chain for a model
           returns the models projected to edit history in a list
           with the most recent first
        """
        result = []
        projection = {'name': True, 'version': True, 'editDetails': True,
                      'derivedFrom': True}
        while modelid:
            model = self.get_raw_model(modelid, projection)
            if model:
                result.append(model)
                modelid = model.get('derivedFrom', None)
            else:
                modelid = None
        return result

    def get_current_version(self, modelname, includetemp=False):
        """Get the most recent version number for a given model name"""
        query = {'name': modelname}
        if not includetemp:
            query.update({'__modeldb_meta.temporary': False})
        result = self.get_raw_model(query, {'version': True})
        return result['version'] if result else "0.0"

    def get_model(self, query, projection=None, bypasscache=False):
        """Load the model from query built into a BgModel object
        See `get_raw_model` for a description of other
        Args:
            bypasscache (bool): if True, load the model from the DB even if it
                might be cached
        """
        # first see if it's in the cache
        if not projection and not bypasscache:
            raw = self.get_raw_model(query, {'_id': True})
            if not raw:
                return None
            # prevents temp models from being loaded from cache:
            # if not raw.get('__modeldb_meta',{}).get('temporary',False):
            model = self._cacher.get(raw['_id'])
            if model:
                return model

        # if we get here, it's not cached
        raw = self.get_raw_model(query, projection)
        model = BgModel.buildfromdict(raw) if raw else None
        if model and not self.is_model_temp(model.id):
            self._cacher.store(model.id, model)
        return model

    _replacekeys = {'$': '\uff04', '.': '\u2024'}
    _findall = tuple(_replacekeys.keys())+tuple(_replacekeys.values())

    @staticmethod
    def encodebson(obj, registry=[], path=tuple()):
        """Some objects in the model may have keys that start with '$' or
        contain periods '.', in particular the querymod and query objects that
        get stored. This function recursively replaces these values with
        their unicode equivalents.

        Args:
            obj:  Any object that will be stored in the DB
            registry: a list of paths to keys that will be overwritten
            path: path to this object from the root document
        """
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                newkey = key

                replacekey = any(k in key for k in ModelDB._findall)
                if replacekey:
                    for k, v in ModelDB._replacekeys.items():
                        newkey = newkey.replace(k, v)
                mypath = path + (newkey,)
                # register altered keys depth-first
                val = ModelDB.encodebson(obj.pop(key), registry, mypath)
                if replacekey:
                    registry.append(mypath)
                obj[newkey] = val
        elif isinstance(obj, (list, tuple)):
            for index, val in enumerate(obj):
                ModelDB.encodebson(val, registry, path+(index,))

        return obj

    @staticmethod
    def decodebson(root, registry):
        """Reverse the subsitutions in encodebson, using the registry to locate
        the changed keys efficiently.
        Args:
            root: the root document returned from mongo
            registry: list of paths to keys to replace
        """
        for path in registry:
            obj = root
            for key in path[:-1]:
                try:
                    obj = obj[key]
                except KeyError:
                    # might be a projection, so ignore
                    break
            oldkey = path[-1]
            if oldkey in obj:
                newkey = path[-1]
                for k, v in ModelDB._replacekeys.items():
                    newkey = newkey.replace(v, k)
                obj[newkey] = obj.pop(oldkey)

        return root

    # todo: implement password-locking for models

    def write_model(self, model, temp=True, bumpversion="major"):
        """Write a modified model to the database.  Only temporary models
        may be directly modified. Attempting to overwrite a non-temporary
        model will result in a new model being generated

        Args:
            model (dict or BgModel): The data to be stored. If the model has
                an '_id' attribute, will attempt to overwrite an existing model

            temp (bool): If true, mark this entry as temporary. Existing non-
                temporay models cannot become temporary

            bumpversion (str): One of "major" or "minor"
        """
        self.testconnection()
        if isinstance(model, BgModel):
            model = model.todict()
        model['__modeldb_meta'] = {'temporary': temp}
        editDetails = model.setdefault('editDetails', {})
        editDetails['date'] = datetime.utcnow().strftime("%F %R UTC")
        if not temp:
            # figure out the version
            oldversion = str(self.get_current_version(model.get('name')))
            oldversion = [int(p) for p in oldversion.split('.')]
            if len(oldversion) < 2:
                oldversion.append(0)
            if bumpversion == "minor":
                newversion = "%d.%d" % (oldversion[0], oldversion[1]+1)
            else:  # treat any other argument as "major"
                newversion = "%d.0" % (oldversion[0]+1)
            model['version'] = newversion
        else:
            # model.pop('version',None)
            model['version'] = editDetails['date']

        # when a temporary model becomes permanent, we give it a new ID so it
        # timesorts properly, then delete the original
        deloldid = None

        if '_id' in model:
            self._cacher.expire(model['_id'])
            # can only overwrite existing models if temporary!
            try:
                istemp = self.is_model_temp(model['_id'])
            except KeyError:  # expected if model isn't in the DB already
                istemp = False
            if (not istemp) or (istemp and not temp):
                if istemp:
                    deloldid = model['_id']
                else:
                    model['derivedFrom'] = model['_id']
                del model['_id']

            else:
                try:
                    res = self._collection.replace_one({'_id': model['_id']},
                                                       model)
                except pymongo.errors.WriteError:
                    # Most likely we have invalid keys
                    registry = []
                    self.encodebson(model, registry, tuple())
                    if not registry:  # no bad keys found, must be other error
                        raise
                    model['__modeldb_meta']['encodedkeys'] = registry
                    # try again
                    res = self._collection.replace_one({'_id': model['_id']},
                                                       model)

        # can't use elif since might have been removed in previous step
        if '_id' not in model:
            try:
                res = self._collection.insert_one(model)
            except pymongo.errors.InvalidDocument:
                # Most likely we have invalid keys
                registry = []
                self.encodebson(model, registry, tuple())
                if not registry:  # no bad keys found, must be other error
                    raise
                model['__modeldb_meta']['encodedkeys'] = registry
                # try again
                res = self._collection.insert_one(model)
            if not temp:
                genevalcache(self.get_model(model['_id']))

        if deloldid:
            self.del_model(deloldid)

        # todo: test the response!
        return model.get('_id')

    def new_model(self, derivedFrom=None, temp=True, name="", simsdb=None):
        """Create a new model in the database, either from scratch or by
        cloning an existing model. By default bump the version number to the
        next available for that name
        Args:
            derivedFrom (str, ObjectID): _id for parent to clone from
            temp (bool): if true (default), mark as temporary
            name (str): name of the new model
            simsdb (str): name pf simsdbview to use
        Returns:
            newmodel (BgModel): new empty or cloned model object
        """
        model = None
        if derivedFrom:
            model = self.get_raw_model(derivedFrom)
            if not model:
                raise KeyError("Model with id %s not found", derivedFrom)
        else:
            model = BgModel(name=name).todict()
        if simsdb:
            model['simsdb'] = simsdb
        newid = self.write_model(model, temp=temp, bumpversion="major")
        return self.get_model(newid)

    def del_model(self, modelid):
        """Delete a model from the database. Not allowed if another model
        derives from it
        """
        # make sure it's an ID and not a model
        modelid = getobjectid(modelid)
        query = self.makequery(modelid)
        model = self.get_raw_model(query, {'derivedFrom': True})
        if not model:
            raise KeyError("No model with id %s" % modelid)
        # see if any models derive from this
        derived = self._collection.count({'derivedFrom': query['_id']})
        if derived:
            raise ValueError("Can't delete model with descendants")

        self._cacher.expire(modelid)
        return self._collection.delete_one(query).deleted_count

    def get_models_list(self, includetemp=False, mostrecentonly=True,
                        projection=None):
        """Get a list of all defined models, just the raw dictionary objects.
        Args:
            includetemp (bool): if true, include temporary models
            mostrecentonly (bool): if true (default), only grab the most recent
                version of each model name
            projection (dict): mongodb projection operator to apply to the
                selection.  Use None to get the full object

        Returns:
            (list): list of models as raw dicts
        """
        self.testconnection()

        projection = projection or {'name': True, 'version': True,
                                    'description': True, 'editDetails': True}

        # use the aggregation pipeline
        pipeline = []
        if not includetemp:
            match = {'$match': {'__modeldb_meta.temporary': False}}
            pipeline.append(match)
        else:
            projection.update({'temporary': '$__modeldb_meta.temporary'})
        pipeline.append({'$sort':
                         OrderedDict((('name', pymongo.ASCENDING),
                                      ('_id', pymongo.DESCENDING)))
                         })
        if mostrecentonly:
            pipeline.extend([
                {'$group': {'_id': '$name', 'mostrecent': {'$first': '$$ROOT'}}},
                {'$replaceRoot': {'newRoot': '$mostrecent'}}
            ])
        if projection is not None:
            pipeline.append({'$project': projection})

        return list(self._collection.aggregate(pipeline))

    def removecache(self, model):
        """ Remove the model from cache
        Args:
            model (BgModel or id): The model to remove
        """
        if hasattr(model, 'id'):
            model = model.id
        self._cacher.expire(model)
