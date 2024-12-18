#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super

import json

from wtforms.fields import (Field, TextAreaField, StringField, HiddenField,
                            SelectField)
from wtforms.compat import text_type
from wtforms import widgets
from wtforms.validators import ValidationError, required
from collections import OrderedDict
from bgmodelbuilder import units
from bgmodelbuilder.common import to_primitive
from flask import current_app
from .widgets import JSONEditor

class DictField(TextAreaField):
    """Render a dictionary as a textarea
    Args:
        label(str): descriptive label, see Field base class
        required_keys(dict): dictionary of required keys with descriptions
        suggested_keys(dict): dictionary of suggested keys with descriptions
            will be presented to form, but deleted if left default
    """
    def __init__(self, label=None, required_keys={}, suggested_keys={},
                 *args, **kwargs):

        super().__init__(label, *args, **kwargs)

        self.required_keys = OrderedDict(required_keys)
        self.suggested_keys = OrderedDict(suggested_keys)
        for key, val in self.required_keys.items():
            self.required_keys[key] = self.paramize(val+" (REQUIRED)")
        for key, val in self.suggested_keys.items():
            self.suggested_keys[key] = self.paramize(val)

    @staticmethod
    def paramize(val):
        if not val.startswith('<'):
            val = '<'+val
        if not val.endswith('>'):
            val = val+'>'
        return val

    def pre_validate(self, form):
        """Make sure required keys have all been filled"""
        for key, val in self.required_keys.items():
            if key not in self.data or self.data[key] == val:
                raise ValidationError("Key '%s' is required"%key)
        for key, val in self.suggested_keys.items():
            if self.data.get(key) == val:
                del self.data[key]

    def process_formdata(self, valuelist):
        if valuelist:
            self.data = OrderedDict()
            for line in valuelist[0].split('\n'):
                if not line.strip():
                    continue
                colon = line.find('=')
                if colon<=0:
                    raise ValidationError("Error at line '%s'; "
                                          "Required format '<key> = <value>'"
                                          %line)
                key = line[:colon].strip()
                val = line[colon+1:].strip()
                self.data[key] = val

    def _value(self):
        if not self.data:
            self.data = OrderedDict()
        data = OrderedDict(**self.data)
        if self.required_keys:
            for key, val in self.required_keys.items():
                data.setdefault(key, val)

        if self.suggested_keys:
            for key, val in self.suggested_keys.items():
                data.setdefault(key, val)

        res = '\n'.join("%s = %s"%(k,v) for k,v in data.items())
        return res

    @property
    def render_kw(self):
        mykw = self._render_kw or {}
        mykw['rows'] = 2 + (len(self.data) if self.data else
                            len(self.required_keys) + len(self.suggested_keys))
        return mykw

    @render_kw.setter
    def render_kw(self, render_kw):
        self._render_kw = render_kw

class StaticField(Field):
    """Render field value as text and never set"""
    def __call__(self, **kwargs):
        return str('<p class="form-control-static">%s</p>'%self.data)

    def populate_obj(self, obj):
        pass

    def _value(self):
        return HTMLString(self.data)


class JSONField(StringField):
    """JSON-encoded field. Set the 'default' argument to list if this expects
    a list, rather than a dict"""
    widget = JSONEditor()

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('default',dict)
        super().__init__(*args, **kwargs)

    def _value(self):
        #if not getattr(self,'data'): #this should be already set...
        #    self.data = self.default()
        if type(self.data) is str:
            return self.data
        if self.data is None:
            self.data = self.default()
        #this is probably redundant, but that should be OK
        self.data = to_primitive(self.data)
        return json.dumps(self.data)

    def process_formdata(self, valuelist):
        if valuelist:
            if valuelist[0] == '':
                valuelist[0] = json.dumps(self.default())
            self.data = valuelist[0]
            try:
                self.data = json.loads(valuelist[0])
                #todo: verify isinstance(self.data, self.expects)???
            except json.JSONDecodeError:
                raise ValidationError(("Field is not valid JSON "
                                       "(keys require double quotes)"))
        #else:
        #    self.data = self.default()

    def process_data(self, value):
        """try to convert everything to json-serializable values"""
        self.data = to_primitive(value)


class NoValSelectField(SelectField):
    """Select field that doesn't validate against choices"""
    def pre_validate(self, form):
        pass



""" Apply this validator to a rendered text field that should be a
pint unit with fixed dimensions"""
def validate_units(unittype=None, nonzero=False):
    if isinstance(unittype,str):
        unittype = units(unittype).dimensionality
    if isinstance(unittype,(units.Quantity, units.Unit)):
        unittype = unittype.dimensionality

    def _validate(form, field):
        try:
            val = units(field.data)
        except units.errors.UndefinedUnitError as e:
            raise ValidationError(e)

        if (unittype is not None and
            getattr(val,'dimensionality',None) != unittype):
            raise ValidationError("Requires unit type %s"%unittype)
        if nonzero and val == 0:
            raise ValidationError("Entry must be non-zero")
        field.data = val
    return _validate


class NumericField(Field):
    """try to reconstruct data as an integer field first, then float"""
    widget = widgets.TextInput()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _value(self):
        if self.raw_data:
            return self.raw_data[0]
        elif self.data is not None:
            return text_type(self.data)
        else:
            return ""

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = int(valuelist[0])
            except ValueError:
                try:
                    self.data = float(valuelist[0])
                except ValueError:
                    self.data = None
                    raise ValueError(self.gettext("Not a valid numeric value"))

class SimsDbField(SelectField):
    def __init__(self, label='Backend', validators=[required()],
                 description="Backend to load simulation data and generate views",
                 render_kw={'class':'form-control'}, **kwargs):
        kwargs.pop('choices', None)
        super().__init__(label=label, validators=validators, description=description,
                         render_kw=render_kw, **kwargs)

    def __call__(self, *args, **kwargs):
        self.choices = [(d,d) for d in current_app.simviews]
        return super().__call__(*args, **kwargs)

