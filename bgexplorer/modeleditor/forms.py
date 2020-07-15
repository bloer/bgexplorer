from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from copy import copy
from textwrap import dedent
from wtforms import (validators, StringField, SubmitField,
                     IntegerField, SelectField, FieldList, FormField,
                     HiddenField, FloatField)

from wtforms import BooleanField
from wtforms.utils import unset_value
from wtforms.widgets import HiddenInput, Select
from wtforms import Form
#FlaskForm needed for wtf.simple_form in flask
from flask_wtf import FlaskForm

from bgmodelbuilder import component, emissionspec

from .fields import (DictField, JSONField, StaticField, validate_units,
                     NoValSelectField, NumericField)
from .widgets import SortableTable, InputChoices, StaticIfExists
from collections import OrderedDict




################ Model Forms ##############################
class SaveModelForm(FlaskForm):
    """Form for editing basic bgmodel details"""
    name = StringField('Model Name', [validators.required()])
    #version = IntegerField("Version", render_kw={'disabled':'disabled'})
    description = StringField("Description", [validators.required()])
    user = StringField("Your name", [validators.required()])
    comment = StringField("Describe your edits", [validators.required()])
    updatesimdata = BooleanField("Update with latest simulation data",
                                 default=True);

    def populate_obj(self, obj):
        obj.name = self.name.data
        #obj.version = self.version.data
        obj.description = self.description.data
        obj.editDetails.update(dict(user=self.user.data,
                                    comment=self.comment.data))




############ Shared stuff ####################3
dist_choices = ('bulk', 'surface_in', 'surface_out')
dist_widget = InputChoices(choices=dist_choices)



################## Component Forms ########################


spectypes = (('CombinedSpec','RadioactiveContam'),
             ('RadonExposure','RadonExposure'),
             ('CosmogenicActivation','CosmogenicActivation'))

class BoundSpecForm(Form):
    """Show mostly static info about a spec registered to a component"""
    id = HiddenField("Spec ID")
    name = StringField("Name", [validators.required()], widget=StaticIfExists(),
                       render_kw={'class':'form-control'})
    category = NoValSelectField("Category", render_kw={'class':'form-control'},
                                choices=copy(spectypes),
                                widget=StaticIfExists(Select()))
    distribution = StringField("Dist.", default=(emissionspec.EmissionSpec.
                                                 _default_distribution),
                               widget=StaticIfExists(dist_widget),
                               render_kw={'class':'form-control'})
    #rate = StaticField("Rate", default='')
    querymod = JSONField("Querymod",render_kw={'class':'form-control'})
    #edit = StaticField("Edit", default="edit")

    #override populate_obj to make new spec if necessary
    def populate_obj(self, obj):
        spec = self.id.data
        if not spec or spec == str(None):
            spec = emissionspec.buildspecfromdict({
                '__class__': self.category.data,
                'name': self.name.data,
                'distribution': self.distribution.data,
                })
        obj.spec = spec
        obj.querymod = self.querymod.data


class BaseComponentForm(FlaskForm):
    """Edit basic info about a component"""
    #todo: is there any way to do this without repeating everything???
    name = StringField("Name", [validators.required()])
    description = StringField("Description")
    comment = StringField("Comment",
                          description="Details of current implementation")
    moreinfo = DictField("Additional Info",
                         suggested_keys=(('owner',"Part owner/designer/buyer"),
                                         ('partnum', "Part number"),
                                         ('vendor', "Part vendor"),
                                         ('datasheet', "URL for datasheet")))
    querymod = JSONField("Query Modifier",
                         description="JSON object modifying DB queries")
    specs = FieldList(FormField(BoundSpecForm, default=component.BoundSpec),
                      label="Emission specs",
                      widget=SortableTable(),
                      render_kw={'_class':"table table-condensed"})


#default component to get units right
defcomp = component.Component()

class ComponentForm(BaseComponentForm):
    """Basic Info plus physical parameters of component"""
    material = StringField("Material")
    mass = StringField("Mass", [validate_units(defcomp.mass)])
    volume = StringField("Volume", [validate_units(defcomp.volume)])
    surface_in = StringField("Inner Surface",
                             [validate_units(defcomp.surface_in)])
    surface_out = StringField("Outer Surface",
                              [validate_units(defcomp.surface_out)])

class PlacementForm(Form):
    component = HiddenField()
    name = StringField("Name",[validators.required()],
                       #widget=StaticIfExists(),
                       render_kw={'class':'form-control'})
    cls = SelectField("Type", [validators.required()],
                      choices=[(d,d) for d in ('Component','Assembly')],
                      widget=StaticIfExists(Select()),
                      render_kw={'class':'form-control'})
    weight = NumericField("Quantity", [validators.required()] ,
                          render_kw={'size':1, 'class':'form-control'})
    querymod = JSONField("Querymod")
    #edit = StaticField("Edit", default="link goes here");
    #override BaseForm process to restructure placements
    class _FakePlacement(object):
        def __init__(self, placement):
            self.component = (placement.component.id
                              if hasattr(placement.component,'id')
                              else placement.component)
            self.name = placement.name
            self.cls = (type(placement.component).__name__
                        if self.component else None)
            self.weight = placement.weight
            self.querymod = placement.querymod

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        if isinstance(obj, component.Placement):
            obj = self._FakePlacement(obj)
        super().process(formdata=formdata, obj=obj, data=data, **kwargs)

    #override populate_obj to make new component if necessary
    def populate_obj(self, obj):
        comp = self.component.data
        if not comp or comp == str(None):
            comp = component.buildcomponentfromdict({
                '__class__': self.cls.data,
                'name': self.name.data
            })
        obj.component = comp
        obj.name = self.name.data
        obj.weight = self.weight.data
        obj.querymod = self.querymod.data

class AssemblyForm(BaseComponentForm):
    """Basic info plus subcomponents"""
    #components = JSONField(default=list, widget=HiddenInput())
    components = FieldList(FormField(PlacementForm,
                                     default=component.Placement),
                           label="Subcomponents",
                           widget=SortableTable(),
                           render_kw={'_class':"table table-condensed"})


############ EmissionSpec forms ##################
#distribution_choices = [(d,d) for d
#                        in emissionspec.EmissionSpec._distribution_types]
#distribution_choices = [(d,d) for d in ('bulk','surface_in','surface_out')]
dist_choices = ('bulk', 'surface_in', 'surface_out', 'flux')

class EmissionspecForm(FlaskForm):
    name = StringField("Name", [validators.required()])
    distribution = StringField("Distribution",[validators.required()],
                               description=("Choices are suggestions; "
                                            "any value is valid"),
                               widget=InputChoices(choices=dist_choices))
    comment = StringField("Comment",
                          description="Comment about current implementation")
    category = StringField("Category", description=("A description category "
                                                    "for grouping sources "
                                                    "(usually leave default)"))
    moreinfo = DictField("Additional Details",
                   suggested_keys=(('reference',"Literature or assay source"),
                                   ('url', "Link to reference"),
                                   ('refdetail', "Summary of reference info"),
                                   ('refdate', "Date reference last checked")))
    normfunc = StringField("Normalization", description=dedent("""\
        Custom rate normalization function. Will be  using 'eval', with
        variables 'component' and 'units' defined. Can also be 'piece' or
        'per piece' indicating that the rate is already normalized"""))

    querymod = JSONField("Querymod", description="Overrides for generating simulation database queries")

class RadioactiveIsotopeForm(Form):
    id = HiddenField("ID")
    name = StringField("Isotope", [validators.required()],
                          render_kw={'size':7,'class':'form-control'})
    rate = StringField("Decay rate",[validate_units(),
                                     validators.input_required()],
                       render_kw={'size':20,'class':'form-control'})
    err  = StringField("Uncertainty",
                       description="Fractional or same units as rate",
                       render_kw={'size':12,'class':'form-control'})
    islimit = BooleanField("Limit?",
                           description="Is this a measurement upper limit?")

def _defaultisotope():
    aspec = emissionspec.RadioactiveContam()
    aspec._id = ""
    return aspec

class RadioactiveContamForm(EmissionspecForm):
    subspecs = FieldList(FormField(RadioactiveIsotopeForm,
                                   default=_defaultisotope),
                         min_entries=1,
                         label="Isotopes",
                         widget=SortableTable(),
                         render_kw={'_class':"table table-condensed"})



defradexp = emissionspec.RadonExposure()
mode_choices = [(d,d) for d in emissionspec.RadonExposure._mode_types]
class RadonExposureForm(EmissionspecForm):
    radonlevel = StringField("Radon Level",
                             [validate_units(defradexp.radonlevel),
                              validators.required()])
    exposure = StringField("Exposure Time",
                           [validate_units(defradexp.exposure),
                            validators.required()])
    column_height = StringField("Plateout Column Height",
                                [validate_units(defradexp.column_height)])
    mode = SelectField("Airflow model", choices = mode_choices)



class CosmogenicIsotopeForm(Form):
    id = HiddenField("ID")
    name = StringField("Isotope",[validators.required()])
    halflife = StringField("Half-life",
                           [validate_units('second'), validators.required()])
    activationrate = StringField("Activation Rate",
                                 [validate_units('1/kg/day'),
                                  validators.required()],
                                 description=("Sea level activation "
                                              "atoms/mass/time"))

defcosmic = emissionspec.CosmogenicActivation()
class CosmogenicActivationForm(EmissionspecForm):
    exposure = StringField("Exposure time",
                           [validate_units(defcosmic.exposure),
                            validators.required()])
    cooldown = StringField("Cooldown time",
                           [validate_units(defcosmic.cooldown)])
    integration = StringField("Measurement time",
                             [validate_units(defcosmic.integration)])
    isotopes = FieldList(FormField(CosmogenicIsotopeForm,
                                   default=emissionspec.CosmogenicIsotope),
                         min_entries=1,
                         label="Isotopes",
                         widget=SortableTable(),
                         render_kw={'_class':"table table-condensed"})




class DustAccumulationForm(RadioactiveContamForm):
    dustmass = StringField("Dust mass",[validate_units(),validators.required()],
                           description=("Units match distribution, "
                                        "e.g. kg/cm**2 for surface"))




############### utilities #######################
def get_form(form, obj):
    """Get the correct form for a component
    Args:
        form: formdata returned from request, passed to Form class
        obj:  object to populate, should be BaseComponent or Emissionspec
    """
    cls = None
    if isinstance(obj, component.Component):
        cls = ComponentForm
    elif isinstance(obj, component.Assembly):
        cls = AssemblyForm

    if not cls:
        raise TypeError("Can't find form for object of type %s"%type(obj))

    return cls(form, obj=obj)


