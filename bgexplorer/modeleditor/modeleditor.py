#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from datetime import datetime
from collections import namedtuple,OrderedDict

import bson
import json

from flask import (Blueprint, render_template, request, redirect, 
                   abort, flash, url_for)
from flask_bootstrap import Bootstrap
import wtforms.widgets 

from . import forms
from .widgets import is_hidden_field 
from ..modeldb import ModelDB
from ..bgmodelbuilder.component import Component, Assembly
from ..bgmodelbuilder import compspec


SpecEntry = namedtuple("SpecEntry","cls form")
    


class ModelEditor(object):
    """Factory class for creating model editor views"""
    def __init__(self, app=None, modeldb=None):
        self.bp = Blueprint('modeleditor', __name__, 
                            static_folder='static', 
                            template_folder='templates')
        self.bp.record(self.onregister)
        self.bp.context_processor(self.context_processor)

        self.modeldb = modeldb or ModelDB()
        
        #set up the spec registry and add the defaults
        self.specregistry = OrderedDict()
        self.registerspectype(compspec.CombinedSpec, 
                              forms.RadioactiveContamForm,
                              "RadioactiveContam")
        self.registerspectype(compspec.RadonExposure, 
                              forms.RadonExposureForm)
        self.registerspectype(compspec.CosmogenicActivation, 
                              forms.CosmogenicActivationForm)
        #dust is not well developed yet...
        #self.registerspectype(compspec.DustAccumulation, 
        #forms.DustAccumulationForm)

        #apply all our routes
        baseroute = '/edit/<modelid>'
        self.bp.add_url_rule('/new', view_func=self.newmodel, 
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/', view_func=self.editmodel,
                             methods=('GET', 'POST'))
        self.bp.add_url_rule(baseroute+'/save', 
                             view_func=self.savemodel,
                             methods=('GET','POST',))
        self.bp.add_url_rule(baseroute+'/newcomponent', 
                             view_func=self.newcomponent,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/delcomponent/<componentid>', 
                             view_func=self.delcomponent,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/newplacement/<parentid>/<childid>',
                             view_func=self.newplacement,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/delplacement/<parentid>/<int:index>',
                             view_func=self.delplacement,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/newspec', view_func=self.newspec,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/delspec/<specid>', 
                             view_func=self.delspec,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/attachspec/<compid>/<specid>', 
                             view_func=self.attachspec,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/detachspec/<compid>/<int:index>',
                       view_func=self.detachspec,
                             methods=('POSt',))
        self.bp.add_url_rule(baseroute+'/setquerymod/<compid>/<specid>', 
                       view_func=self.setquerymod,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/editcomponent/<componentid>', 
                       view_func=self.editcomponent,
                             methods=('GET', 'POST'))
        self.bp.add_url_rule(baseroute+'/editspec/<specid>', 
                       view_func=self.editspec,
                             methods=('GET', 'POST'))
    
        
        if app:
            self.init_app(app)
            
    
    def onregister(self, setupstate):
        #make sure bootstrap is registered
        if not 'bootstrap' in setupstate.app.blueprints:
            Bootstrap(setupstate.app)
        setupstate.app.jinja_env.globals['bootstrap_is_hidden_field'] = \
            is_hidden_field
        
        #initialize the modeldb
        #todo: make sure this only gets done once
        self.modeldb.init_app(setupstate.app)
        
        #update the spec form choices
        forms.BoundSpecForm.category.choices = [
            (val.cls,name) for name, val in self.specregistry.items()
        ]

    def init_app(self, app, url_prefix='/models'):
        app.register_blueprint(self.bp, url_prefix=url_prefix)

    def registerspectype(self, cls, form, name=None):
        """Register a new ComponentSpec class and form for editing
        Args:
            cls: class or constructor, should inherit from ComponentSpec
            form: WTForm for editing, should inherit from CompSpecForm
            name (str): Name for this class, if None, use cls.__name__
        """
        name = name or cls.__name__
        self.specregistry[name] = SpecEntry(cls, form)
        
    
    def context_processor(self):
        """Register global variables available to templates"""
        return dict(spectypes=list(self.specregistry.keys()))
    
    ###### Utility functions for DB access ##########
    def getmodelordie(self, modelid):
        """try to get model with modelid from the db, else return 404"""
        #todo: enforce that the model is temporary
        if not isinstance(modelid, bson.ObjectId):
            modelid = bson.ObjectId(modelid)
        model = self.modeldb.get_model(modelid)
        if not model:
            abort(404, "Model with ID %s not found"%modelid)
        return model

    def getcomponentordie(self, model, compid):
        """try to find the component with ID compid in model or return 404"""
        comp = model.components.get(compid)
        if not comp:
            abort(404, "Model %s has no component with ID %s" 
                  %(model._id, compid))
        return comp

    def getspecordie(self, model, specid):
        """try to find the compspec with ID specid in model or return 404"""
        spec = model.specs.get(specid)
        if not spec:
            abort(404, "Model %s has no component soec with ID %s" %
                  (model._id, specid))
        return spec


    ##### modeleditor API #######
    #todo: implement some caching here!
    def newmodel(self):
        """Create a new bare model or clone an existing one for editing"""
        derivedFrom = request.values.get('derivedFrom', None)
        newmodel = self.modeldb.new_model(derivedFrom)
        #todo: handle error no model returned, probably DB down
        return redirect(url_for('.editmodel', modelid=str(newmodel.id)))

    #todo: implement delete model

    #all endpoints build on the same route from here out
    
    def editmodel(self, modelid):
        """return a page with forms for model editing"""
        model = self.getmodelordie(modelid)
        return render_template('editmodel.html', model=model)

    def savemodel(self, modelid):
        """Save the model to the DB, making sure all edit details fields 
        validated
        """
        model = self.getmodelordie(modelid)
        if 'date' in model.editDetails:
            del model.editDetails['date']
            form = forms.SaveModelForm(request.form, model)
            if request.method == 'POST' and form.validate():
                form.update_obj(model)
                model.editDetails['date'] = str(datetime.now())
                #this should already be set, but just to make sure:
                model.version = self.modeldb.get_current_version(model.name)+1
                self.modeldb.write_model(model, temp=False)
                flash("Model %s version %d successfully saved"%(model.name, 
                                                                model.version),
                      'success')
                return redirect(url_for("index"))

        return render_template('savemodel.html', model=model, form=form)

    #todo: implement delete functionality

    ###Component/spec editing API
    ###Actions are:
    # new component (child of X)
    # delete component
    # new placement 
    # delete placement
    # new spec
    # delete spec
    # place spec
    # remove spec
    # edit query modifier
    # edit component (metadata, etc)
       
    def newcomponent(self, modelid):
        model = self.getmodelordie(modelid)
        clonefrom = request.values.get('clonefrom')
        if clonefrom:
            oldcomp = self.getcomponentordie(model, clonefrom)
            newcomp = oldcomp.clone()
        else:
            newcomp = (Assembly() if request.values.get('class') == 'Assembly' 
                       else Component())
        parentid = request.values.get('parent')
        if parentid:
            parent = self.getcomponentordie(model, parentid)
            replace = int(request.values.get('replaceAt',-1))
            if replace >= 0 and replace < len(parent.components):
                placement = parent.components[replace]
                placement.component.placements.remove(placement)
                placement.component = newcomp
                newcomp.placements.add(placement)
            else:
                parent.addcomponent(newcomp)
        
        model.components[newcomp.id] = newcomp
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid, 
                                componentid=newcomp.id))
        
    def delcomponent(self, modelid, componentid):
        model = self.getmodelordie(modelid)
        component = self.getcomponentordie(model, componentid)
        #remove references from parents
        for placement in component.placements:
            if placement.parent:
                placement.parent.delcomponent(placement)
        #and from the registry
        del model.components[componentid]
        self.modeldb.write_model(model)
        return redirect(url_for('.editmodel', modelid=modelid))

    def newplacement(self, modelid, parentid, childid):
        model = self.getmodelordie(modelid)
        parent = self.getcomponentordie(model, parentid)
        child = self.getcomponentordie(model, childid)
        #we also call this for rearranging; if we're already a child, remove it
        if child in parent.getcomponents(deep=False, withweights=False):
            parent.delcomponent(child)
        number = request.values.get('number',1)
        index = request.values.get('index')
        parent.addcomponent((child,number), index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid, 
                                componentid=parentid))
        
    def delplacement(self, modelid, parentid, index):
        model = self.getmodelordie(modelid)
        parent = self.getcomponentordie(model, parentid)
        parent.delcomponent(index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid, 
                                componentid=parentid))

    def newspec(self, modelid):
        model = self.getmodelordie(modelid)
        newspec = None
        clonefrom = request.values.get('clonefrom')
        if clonefrom:
            prior = self.getspecordie(model, clonefrom)
            newspec = prior.clone()
        else:
            spectype = request.values.get('type', 'RadioactiveContam')
            if spectype not in self.specregistry:
                abort(404, "Unknown ComponentSpec type ", spectype)
            newspec = self.specregistry[spectype].cls()

        model.specs[newspec.id] = newspec
        self.modeldb.write_model(model)
        return redirect(url_for('.editspec',modelid=modelid, specid=newspec.id))

    def delspec(self, modelid, specid):
        model = self.getmodelordie(modelid)
        spec = self.getspecordie(model, specid)
        #remove all references
        for comp in list(spec.appliedto):
            comp.delspec(spec)
        del model.specs[spec.id]
        self.modeldb.write_model(model)
        return redirect(url_for('.editmodel', modelid=modelid))

    def attachspec(self, modelid, compid, specid):
        model = self.getmodelordie(modelid)
        comp = self.getcomponentordie(model, compid)
        spec = self.getspecordie(model, specid)
        index = request.values.get('index')
        comp.addspec(spec, index=index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid, 
                                componentid=compid))

    def detachspec(self, modelid, compid, index):
        model = self.getmodelordie(modelid)
        comp = self.getcomponentordie(model, compid)
        comp.delspec(index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid, 
                                componentid=compid))

    def setquerymod(self, modelid, compid, specid):
        model = self.getmodelordie(modelid)
        comp = self.getcomponentordie(model, compid)
        querymod = request.values.get('querymod')
        if querymod:
            if isinstance(querymod, str):
                querymod = json.loads(querymod)
                #todo: implement error handling here
            comp.querymods[specid] = querymod
        elif specid in comp.querymods:
            del comp.querymods[specid]

        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', 
                                modelid=modelid, componentid=compid))

    def editcomponent(self, modelid, componentid):
        """return a page with forms for component editing"""
        #todo: do we need to pass different forms for component types here? 
        model = self.getmodelordie(modelid)
        comp = self.getcomponentordie(model, componentid)
        form = forms.get_form(request.form, comp)
        if request.method == 'POST' and form.validate():
            form.populate_obj(comp)
            self.modeldb.write_model(model)
            flash("Changes to component '%s' successfully saved"%comp.name,
                  'success')
            #reload from the DB to make sure all references are populated
            model = self.getmodelordie(modelid)
        return render_template('editmodel.html', model=model, 
                               editcomponent=comp, form=form)

    def editspec(self, modelid, specid):
        """return a page with forms for componentspec editing"""
        model = self.getmodelordie(modelid)
        spec = self.getspecordie(model, specid)
        #find the correct form
        possibleforms = [entry.form for entry in self.specregistry.values()
                         if entry.cls == type(spec)]
        if len(possibleforms) < 1:
            abort(404,"No form defined for class %s",type(spec).__name__)
        form = possibleforms[0](request.form, obj=spec)
        if request.method == 'POST' and form.validate():
            form.populate_obj(spec)
            self.modeldb.write_model(model)
            flash("Changes to spec '%s' successfully saved"%spec.name,
                  'success')
            #reload from the DB to make sure all references are populated
            model = self.getmodelordie(modelid)
        return render_template('editmodel.html', model=model, editspec=spec, 
                               form=form)

