from wtforms import (validators, StringField, SubmitField, FileField,
                     IntegerField, SelectField, FieldList, FormField,
                     HiddenField, FloatField, TextField, TextAreaField)
import traceback
from wtforms import BooleanField
from wtforms.utils import unset_value
from wtforms.widgets import HiddenInput, Select, Input
from wtforms import Form
#FlaskForm needed for wtf.simple_form in flask
from flask_wtf import FlaskForm
from flask import url_for
from datetime import datetime
from ..modeleditor.forms import RadioactiveContamForm
from bgmodelbuilder.emissionspec import CombinedSpec
from bgmodelbuilder.mappable import Mappable

def _strnow():
    return str(datetime.utcnow())

class AssayEntry(Mappable):
    """ Data representing an assay measurement. Designed to be imported into
    a specific model and keep the reference """
    def __init__(self, specs=None, sampleinfo=None, measurementinfo=None,
                 dataentry=None, attachments=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.specs = specs
        if isinstance(specs, dict):
            self.specs = CombinedSpec(**specs)
        elif specs is None:
            self.specs = CombinedSpec()
        if self.specs.category in ('CombinedSpec', 'RadioactiveContam'):
            self.specs.category = ''
        self.sampleinfo = sampleinfo or {}
        self.measurementinfo = measurementinfo or {}
        self.dataentry = dataentry or {}
        self.attachments = attachments or []

    def tospec(self):
        """ Convert to a CombinedSpec for import to a model """
        out = self.specs

        out.comment = '(Imported from assaydb)'
        out.moreinfo = {'assaydb_id' : self.id,
                        'refdate':  _strnow()}
        def _setifset(val, key):
            if val:
                out.moreinfo[key] = val
        try:
            myurl = url_for('.detail', assayid=self.id)
        except RuntimeError:
            myurl = None
        out.moreinfo['reference'] = 'assaydb'
        _setifset(myurl, 'url')
        _setifset(self.sampleinfo.get('vendor'), 'vendor')
        _setifset(self.sampleinfo.get('batch'), 'batch')
        detail = ''
        if self.sampleinfo.get('sampleid'):
            detail = ' SampleID %s ' % self.sampleinfo['sampleid']
        if self.sampleinfo.get('description'):
            detail += ' ' + self.sampleinfo['description']
        out.comment += detail

        return out

    @property
    def name(self):
        return self.specs.name


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

class PerPieceField(BooleanField):
    def process_data(self, value):
        self.data = bool(value == 'piece')

    def populate_obj(self, obj, name):
        setattr(obj, name, 'piece' if self.data else '')

class SampleInfoForm(Form):
    sampleid = TextField('Sample ID')
    description = TextField('Description')
    vendor = TextField('Vendor/producer')
    batch = TextField('Batch number/ID')
    owner = TextField('Sample owner')
    ownercontact = TextField('Owner contact info')
    notes = TextAreaField('Additional Notes')

class MeasurementInfoForm(Form):
    technique = TextField('Measurement technique')
    institution = TextField('Institution/Location')
    instrument = TextField('Instrument used')
    date = TextField('Measurement date')
    operator = TextField('Operator') #, description='Name of person who made the measurement')
    operatorcontact = TextField('Operator contact info')
    notes = TextAreaField('Additional Notes')

class DataEntryInfoForm(Form):
    user = TextField('User', [validators.required()], description="person who entered the data")
    usercontact = TextField('User contact info')
    reference = TextField('Original Reference')
    url = TextField('URL for original reference')
    created = HiddenField(default=_strnow)
    modified = HiddenField(default=_strnow)


class AssaySpecForm(RadioactiveContamForm):
    normfunc = PerPieceField('Results are per-piece?')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.csrf_token
        del self.querymod
        del self.moreinfo
        del self.comment

class AssayForm(FlaskForm):
    specs = FormField(AssaySpecForm, "Emission Specs")
    dataentry = DictFormField(DataEntryInfoForm, "Data Entry Details")
    sampleinfo = DictFormField(SampleInfoForm, "Sample Details")
    measurementinfo = DictFormField(MeasurementInfoForm, "Measurement Details")
    save = AnonymousSubmitField("Save")

    @property
    def name(self):
        return self.specs.name

