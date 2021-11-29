from flask import (Blueprint, render_template, request, redirect, abort,
                   flash, url_for, current_app, jsonify, send_file)
import pymongo
from bson import ObjectId
from io import BytesIO
from bgmodelbuilder.emissionspec import RadioactiveContam, CombinedSpec, buildspecfromdict
from ..modeleditor.forms import RadioactiveContamForm
from wtforms.fields import HiddenField, FormField
from copy import copy
from .forms import AssayEntry, AssayForm
from ..utils import getmodelordie, get_modeldb
import datetime
import hashlib
import logging
log = logging.getLogger(__name__)

""" AssayDB maintains an EmissionSpecs database not attached to any specific
model. Entries in this database can be imported into models, and retain
association, but do not automatically update if the original entry changes.

The AssaysDB object is both a blueprint and a database to be accessed by
other blueprints.
"""

class AssayDB(object):
    def __init__(self, dburi=None, collection='assays', app=None):
        self.bp = Blueprint('assaydb', __name__,
                            static_folder='static',
                            template_folder='templates')

        self.addendpoints()

        self.app = app
        self._collectionName = collection
        self._client = None
        self._database = None
        self._collection = None

        if dburi:
            self.connect(dburi)
        if app:
            self.init_app(app)

    _default_uri = 'mongodb://localhost/assaydb'
    def connect(self, dburi=None):
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
        self._collection.create_index('specs.name', unique=True)

    def init_app(self, app, url_prefix='/assays'):
        """Initialize from configuration parameters in a Flask app"""
        self.app = app
        dburi = app.config.setdefault('ASSAYDB_URI', self._default_uri)
        self._collectionName = app.config.setdefault('ASSAYDB_COLLECTION',
                                                     'assays')
        self.connect(dburi)
        app.register_blueprint(self.bp, url_prefix=url_prefix)
        app.extensions['AssayDB'] = self

    _defpro = {'attachments.blob': False}

    def get(self, assayid, doabort=True, raw=False, projection=None):
        project = projection or self._defpro
        result = self._collection.find_one(assayid, projection)
        if result is None:
            msg = f"No assay entry with id {assayid}"
            if doabort:
                abort(404, msg)
            else:
                raise KeyError(msg)
        if not raw:
            result = AssayEntry(**result)
        return result

    def find(self, query=None, raw=False):
        result = self._collection.find(query, projection=self._defpro)
        if not raw:
            result = (AssayEntry(**r) for r in result)
        return result

    def save(self, entry):
        # pymongo needs a dict, so convert if it is a real assay
        entry = copy(entry.__dict__)
        try:
            entry['specs'] = entry['specs'].todict()
            entry['specs'].pop('__class__', None)
        except KeyError:
            abort(400, "AssayEntry requires emissions details")
        if entry.get('_id') is None:
            entry.pop('_id', None)
            self._collection.insert_one(entry)
        else:
            self._collection.replace_one({'_id': entry['_id']}, entry, upsert=True)
        return entry['_id']

    def addendpoints(self):
        @self.bp.before_request
        def before_request():
            if not request.form:
                request.form = None

        @self.bp.route('/')
        def index():
            return render_template('assays_overview.html', assays=self.find())

        @self.bp.route('/tomodel/<modelid>', methods=('GET', 'POST'))
        def tomodel(modelid):
            if request.method == 'POST':
                query = {'_id': {'$in': request.form.getlist('id')}}
                entries = list(self.find(query))
                if entries:
                    model = getmodelordie(modelid, toedit=True)
                    specid = None
                    for entry in entries:
                        ref = entry.tospec()
                        model.specs[ref.id] = ref
                        if not specid:
                            specid = ref.id
                    get_modeldb().write_model(model)
                    flash(f"{len(entries)} entries successfully imported", 'success')
                    return redirect(url_for('modeleditor.editspec',
                                    modelid=modelid, specid=specid))
                else:
                    flash("No entries selected!", 'error')
            return render_template('assays_overview.html', assays=self.find(),
                                   tomodel=modelid)


        @self.bp.route('/<assayid>')
        def detail(assayid):
            # placeholder until we get a better view page
            #return jsonify(self.get(assayid, raw=True))
            assay = self.get(assayid)
            form = AssayForm(obj=assay)
            return render_template('assaydetail.html', assay=assay, form=form)

        @self.bp.route('/new', methods=('GET', 'POST'))
        @self.bp.route('/edit/<assayid>', methods=('GET', 'POST'))
        def edit(assayid=None):
            entry = None
            if assayid:
                entry = self.get(assayid)
            else:
                subspecs = [RadioactiveContam(iso) for iso in ('U238', 'Th232', 'K40')]
                entry = AssayEntry(specs=CombinedSpec(name='', subspecs=subspecs))
            form = AssayForm(request.form, obj=entry)
            if request.method == 'POST' and form.validate():
                form.populate_obj(entry)
                try:
                    assayid = self.save(entry)
                except pymongo.errors.PyMongoError as e:
                    flash(f"Error saving entry: {e}", 'error')
                else:
                    flash(f"Successfully saved entry {entry.name}", 'success')
                    return redirect(url_for('.edit', assayid=assayid))
            return render_template('edit_assay.html', form=form, entry=entry,
                                   assayid=assayid)

        @self.bp.route('/delete', methods=('POST',))
        def delete():
            deleted = 0
            query = {'_id': {'$in': request.form.getlist('id')} }
            result = self._collection.delete_many(query)
            flash(f"Successfully deleted {result.deleted_count} entries",
                  'warning')
            return redirect(url_for('.index'))

        @self.bp.route('/export', methods=('GET', 'POST'))
        def exportentries():
            query = {'_id': {'$in': request.values.getlist('id')}}
            return jsonify(list(self.find(query, raw=True)))

        @self.bp.route('/import', methods=('GET', 'POST'))
        def importentries():
            abort(501, "This action is not yet implemented")

        @self.bp.route('/addattachments/<assayid>', methods=('POST',))
        def addattachments(assayid):
            assay = self.get(assayid) # we don't need this, but checks that id exists
            files = request.files.getlist('fupload')
            for _file in files:
                blob = _file.read()
                finfo = dict(_id=ObjectId(),
                             filename=_file.filename,
                             mimetype=_file.mimetype,
                             size=len(blob),
                             etag=hashlib.sha1(blob).hexdigest(),
                             blob=blob,
                             )
                try:
                    self._collection.update_one({'_id':assayid},
                                                {'$push': {'attachments': finfo}})
                except Exception as e:
                    log.error(f"Error adding attachment {e}")
                    flash(f"Error adding attachment: {e}","error")
            flash(f"Processed {len(files)} attachments", 'info')

            return redirect(url_for('.edit', assayid=assayid))

        @self.bp.route('/getattachment/<assayid>/<attachmentid>')
        def getattachment(assayid, attachmentid):
            attachmentid = ObjectId(attachmentid)
            query = {'_id': assayid, 'attachments._id': attachmentid}
            projection = {'attachments.$': 1}
            doc = self._collection.find_one(query, projection)
            if not doc:
                abort(404, "Can't find requested attachment")
            doc = doc['attachments'][0]
            return send_file(BytesIO(doc['blob']), mimetype=doc['mimetype'],
                             download_name=doc['filename'], etag=doc['etag'],
                             last_modified=doc['_id'].generation_time)



        @self.bp.route('delattachment/<assayid>/<attachmentid>', methods=('POST',))
        def delattachment(assayid, attachmentid):
            attachmentid = ObjectId(attachmentid)
            assay = self.get(assayid)
            filename = None
            for attachment in assay.attachments:
                if attachment['_id'] == attachmentid:
                    filename = attachment['filename']
            if not filename:
                abort(404, f"No attachment with ID {attachmentid} on assay {assay.name}")

            mod = {'$pull': {'attachments': {'_id': attachmentid}}}
            try:
                result = self._collection.update_one({'_id':assayid}, mod)
                print(result.modified_count)
            except Excepception as e:
                msg = f"Exception updating assay attachments: {e}"
                log.error(msg)
                flash(msg, 'error')
            else:
                flash(f"Successfully deleted attachment from assay {assay.name}",
                      'success')
            return redirect(url_for('.edit', assayid=assayid))
