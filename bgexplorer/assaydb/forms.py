from wtforms import (validators, StringField, SubmitField, FileField,
                     IntegerField, SelectField, FieldList, FormField,
                     HiddenField, FloatField, TextField, TextAreaField)

from wtforms import BooleanField
from wtforms.utils import unset_value
from wtforms.widgets import HiddenInput, Select
from wtforms import Form
#FlaskForm needed for wtf.simple_form in flask
from flask_wtf import FlaskForm
from flask import url_for
from datetime import datetime
from ..modeleditor.forms import RadioactiveContamForm
from bgmodelbuilder.emissionspec import CombinedSpec

def _strnow():
    return str(datetime.utcnow())

class AssayEntry(CombinedSpec):
    """ Data representing an assay measurement. Designed to be imported into
    a specific model and keep the reference """
    def __init__(self, name='', subspecs=[], owner='', sampleinfo=None,
                 measurementinfo=None, dataentry=None, attachments=None,
                 **kwargs):
        kwargs.pop('__class__', None)
        print(kwargs)
        super().__init__(name, subspecs, **kwargs)
        self.owner = owner
        self.sampleinfo = sampleinfo or {}
        self.measurementinfo = measurementinfo or {}
        self.dataentry = dataentry or {}
        self.attachments = attachments or []
        if self.category == 'AssayEntry':
            self.category = ''

    def tospec(self):
        """ Convert to a CombinedSpec for import to a model """
        out = CombinedSpec()
        for key in out.__dict__:
            if key != '_id':
                setattr(out, key, getattr(self, key, None))

        out.comment = '(Imported from assaydb)'
        out.moreinfo = {'assaydb_id' : self.id,
                        'assaydb_import':  _strnow()}
        def _setifset(val, key):
            if val:
                out.moreinfo[key] = val
        try:
            myurl = url_for('.detail', assayid=self.id)
        except RuntimeError:
            myurl = None
        _setifset(self.dataentry.get('reference', 'assaydb'), 'reference')
        _setifset(self.dataentry.get('url',  myurl), 'url')
        _setifset(self.sampleinfo.get('vendor'), 'vendor')
        _setifset(self.sampleinfo.get('batch'), 'batch')
        detail = ''
        if self.sampleinfo.get('sampleid'):
            detail = ' SampleID %s ' % self.sampleinfo['sampleid']
        if self.sampleinfo.get('description'):
            detail += ' ' + self.sampleinfo['description']
        out.comment += detail

        return out


class DictFormField(FormField):
    """ Form that populates dict keys rather than attributes """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = 'FormField'

    def populate_obj(self, obj, name):
        setattr(obj, name, self.form.data)

class AnonymousSubmitField(SubmitField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = 'SubmitField'

    def populate_obj(self, obj, name):
        pass

class SampleInfoForm(Form):
    sampleid = TextField('Sample ID')
    description = TextField('Description')
    owner = TextField('Sample owner')
    ownercontact = TextField('Owner contact info')
    vendor = TextField('Vendor/producer')
    batch = TextField('Batch number/ID')
    notes = TextAreaField('Additional Notes')

class MeasurementInfoForm(Form):
    operator = TextField('Operator', description='Name of person who made the measurement')
    operatorcontact = TextField('Operator contact info')
    date = TextField('Measurement date')
    institution = TextField('Institution/Location')
    technique = TextField('Measurement technique')
    instrument = TextField('Instrument used')
    notes = TextAreaField('Additional Notes')

class DataEntryInfoForm(Form):
    user = TextField('User', [validators.required()], description="person who entered the data")
    usercontact = TextField('User contact info')
    reference = TextField('Original Reference')
    url = TextField('URL for original reference')
    created = HiddenField(default=_strnow)
    modified = HiddenField(default=_strnow)


class AssayForm(RadioactiveContamForm):
    querymod = HiddenField(default={})
    normfunc = HiddenField(default='')
    moreinfo = HiddenField(default={})
    comment = HiddenField(default='')

    sampleinfo = DictFormField(SampleInfoForm, "Sample Details")
    measurementinfo = DictFormField(MeasurementInfoForm, "Measurement Details")
    dataentry = DictFormField(DataEntryInfoForm, "Data Entry Details")
    save = AnonymousSubmitField("Save")
