from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from textwrap import dedent
from wtforms import (validators, StringField, SubmitField, BooleanField, 
                     IntegerField, SelectField, FieldList, FormField, 
                     HiddenField, FloatField)
from wtforms.widgets import HiddenInput, Select
from wtforms import Form
#FlaskForm needed for wtf.simple_form in flask 
from flask_wtf import FlaskForm

from  ..bgmodelbuilder import component
from ..bgmodelbuilder import compspec

from .fields import DictField, JSONField, StaticField, validate_units 
from .widgets import SortableTable, InputChoices, StaticIfExists

    
################ Model Forms ##############################
class SaveModelForm(FlaskForm):
    """Form for editing basic bgmodel details"""
    name = StringField('Model Name', [validators.required()])
    version = IntegerField("Version", render_kw={'disabled':'disabled'})
    description = StringField("Description", 
                              description="What does this model include?")
    editDetails = DictField("Change log", 
                            required_keys={'user': 'Your name',
                                           'comment': 'Describe your edits'})
    submit = SubmitField()

    

################## Component Forms ########################

#this won't work because the default CompSpec will have a class
#how to pass list of valid classes? 
class RegisteredSpecForm(Form):
    """Show mostly static info about a spec registered to a component"""
    id = HiddenField("ID")
    name = StringField("Name", widget=StaticIfExists())
    category = StringField("Category", widghet=StaticIfExists())
    distribution = StringField("Dist.", widget=StaticIfExists())
    rate = StaticField("Rate", default='')

    
    #this won't work because saying "obj=" only overwrites the local name
    def populate_obj(self, obj):
        if self.id.data:
            obj = self.id.data
        else:
            #make a new spec
            obj = compspec.buildspecfromdict({
                'name': self.name.data,
                '__class__': self.category.data,
                'distribution': self.distribution.data
                })

class BaseComponentForm(FlaskForm):
    """Edit basic info about a component"""
    #todo: is there any way to do this without repeating everything???
    name = StringField("Name", [validators.required()])
    description = StringField("Description")
    comment = StringField("Comment", 
                          description="Details of current implementation")
    moreinfo = DictField("Additional Info",
                         suggested_keys={'owner':"Person responsible for part",
                                         'partnum': "Part number",
                                         'vendor': "Part vendor",
                                         'datasheet': "URL for datasheet"})
    querymod = JSONField("Query Modifier",
                         description="JSON object modifying DB queries")


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
    name = StringField("Name",widget=StaticIfExists())
    cls = SelectField("Type",
                      choices=[(d,d) for d in ('Component','Assembly')],
                      widget=StaticIfExists(Select()))
    weight = FloatField("Quantity")
    edit = StaticField("Edit", default="link goes here");
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
        obj.weight = self.weight.data

class AssemblyForm(BaseComponentForm):
    """Basic info plus subcomponents"""
    #components = JSONField(default=list, widget=HiddenInput())
    components = FieldList(FormField(PlacementForm,
                                     default=component.Placement),
                           label="Subcomponents",
                           widget=SortableTable(),
                           render_kw={'_class':"table table-condensed"})
    

############ ComponentSpec forms ##################
#distribution_choices = [(d,d) for d 
#                        in compspec.ComponentSpec._distribution_types]
#distribution_choices = [(d,d) for d in ('bulk','surface_in','surface_out')]
dist_choices = ('bulk', 'surface_in', 'surface_out')

class CompSpecForm(FlaskForm):
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
                   suggested_keys={'reference':"Literature or assay source",
                                   'url': "Link to reference",
                                   'refdetail': "Summary of reference info",
                                   'refdate': "Date reference last checked"})
    normfunc = StringField("Normalization", description=dedent("""\
        Custom rate normalization function. Will be  using 'eval', with 
        variables 'component' and 'units' defined. Can also be 'piece' or 
        'per piece' indicating that the rate is already normalized"""))
    

class RadioactiveIsotopeForm(Form):
    isotope = StringField("Isotope", [validators.required()],
                          render_kw={'size':7,'class':'form-control'})
    rate = StringField("Decay rate",[validate_units(), 
                                     validators.input_required()],
                       render_kw={'size':20,'class':'form-control'})
    err  = StringField("Uncertainty", 
                       description="Fractional or same units as rate",
                       render_kw={'size':12,'class':'form-control'})
    islimit = BooleanField("Limit?",
                           description="Is this a measurement upper limit?")

class RadioactiveContamForm(CompSpecForm):
    subspecs = FieldList(FormField(RadioactiveIsotopeForm,
                                   default=compspec.RadioactiveContam), 
                         min_entries=1,
                         label="Isotopes",
                         widget=SortableTable(),
                         render_kw={'_class':"table table-condensed"})
    
                                   
                   
defradexp = compspec.RadonExposure()
mode_choices = [(d,d) for d in compspec.RadonExposure._mode_types]
class RadonExposureForm(CompSpecForm):
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
    name = StringField("Isotope",[validators.required()])
    halflife = StringField("Half-life", 
                           [validate_units('second'), validators.required()])
    activationrate = StringField("Activation Rate",
                                 [validate_units('1/kg/day'), 
                                  validators.required()],
                                 description=("Sea level activation "
                                              "atoms/mass/time"))
    
defcosmic = compspec.CosmogenicActivation()
class CosmogenicActivationForm(CompSpecForm):
    exposure = StringField("Exposure time", 
                           [validate_units(defcosmic.exposure),
                            validators.required()])
    cooldown = StringField("Cooldown time",
                           [validate_units(defcosmic.cooldown)])
    integration = StringField("Measurement time",
                             [validate_units(defcosmic.integration)])
    isotopes = FieldList(FormField(CosmogenicIsotopeForm,
                                   default=compspec.CosmogenicIsotope),
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
        obj:  object to populate, should be BaseComponent or CompSpec
    """
    cls = None
    if isinstance(obj, component.Component):
        cls = ComponentForm
    elif isinstance(obj, component.Assembly):
        cls = AssemblyForm
    
    if not cls:
        raise TypeError("Can't find form for object of type %s"%type(obj))

    return cls(form, obj=obj)
        

