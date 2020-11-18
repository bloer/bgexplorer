#python 2/3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
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
from bgmodelbuilder.component import Component, Assembly
from bgmodelbuilder import emissionspec, bgmodel, units
from ..utils import get_simsdb, getmodelordie, getcomponentordie, getspecordie


SpecEntry = namedtuple("SpecEntry","cls form")



class ModelEditor(object):
    """Factory class for creating model editor views
    TODO: write documentation
    """
    def __init__(self, app=None, modeldb=None):
        self.bp = Blueprint('modeleditor', __name__,
                            static_folder='static',
                            template_folder='templates')
        self.bp.record(self.onregister)
        self.bp.context_processor(self.context_processor)

        @self.bp.before_request
        def before_request():
            if not request.form:
                request.form = None


        @self.bp.app_template_global()
        def savemodelform(model):
            return forms.SaveModelForm(obj=model, prefix='savemodel')

        self.modeldb = modeldb or ModelDB()

        #set up the spec registry and add the defaults
        self.specregistry = OrderedDict()
        self.registerspectype(emissionspec.CombinedSpec,
                              forms.RadioactiveContamForm,
                              "RadioactiveContam")
        self.registerspectype(emissionspec.RadonExposure,
                              forms.RadonExposureForm)
        self.registerspectype(emissionspec.CosmogenicActivation,
                              forms.CosmogenicActivationForm)
        #dust is not well developed yet...
        #self.registerspectype(emissionspec.DustAccumulation,
        #forms.DustAccumulationForm)

        #apply all our routes
        baseroute = '/edit/<modelid>'
        self.bp.add_url_rule('/new', view_func=self.newmodel,
                             methods=('POST',))
        self.bp.add_url_rule('/del', view_func=self.delmodel,
                             methods=('POST',))
        self.bp.add_url_rule(baseroute+'/', view_func=self.editmodel,
                             methods=('GET', 'POST'))
        self.bp.add_url_rule(baseroute+'/save',
                             view_func=self.savemodel,
                             methods=('POST',))
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
        self.bp.add_url_rule(baseroute+'/bindsimdata',
                             view_func=self.bindsimdata,
                             methods=('GET', 'POST'))
        @self.bp.route('/help')
        def help():
            return render_template('help.html')

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
        """Register a new EmissionSpec class and form for editing
        Args:
            cls: class or constructor, should inherit from EmissionSpec
            form: WTForm for editing, should inherit from EmissionspecForm
            name (str): Name for this class, if None, use cls.__name__
        """
        name = name or cls.__name__
        self.specregistry[name] = SpecEntry(cls, form)


    def context_processor(self):
        """Register global variables available to templates"""
        return dict(spectypes=list(self.specregistry.keys()),
                    forms=forms)

    def addlinks(self, form, modelid):
        """Replace names in subfield forms with links"""
        for field in form:
            if hasattr(field,'entries'):
                for entry in field:
                    href=None
                    field=None
                    if entry.form_class is forms.PlacementForm:
                        href = url_for('.editcomponent',modelid=modelid,
                                       componentid=entry['component'].data)
                        field = 'cls'
                    elif entry.form_class is forms.BoundSpecForm:
                        href = url_for('.editspec', modelid=modelid,
                                       specid=entry['id'].data)
                        field = 'name'
                    if href:
                        entry[field].link = href
                        #entry[field].data = ("<a href='%s'>%s</a>"
                        #                      %(href, entry[field].data))



    ##### modeleditor API #######
    #todo: implement some caching here!
    def newmodel(self):
        """Create a new bare model or clone an existing one for editing"""
        name = ""
        simsdbview = None
        if request.form:
            name = request.form.get('name',name)
            simsdbview = request.form.get('backend', simsdbview)
        importfile = None
        if request.files:
            importfile = request.files.get('importmodel',importfile)

        if importfile:
            #try to convert file data
            try:
                filecontents = importfile.read()
                rawmodel = json.loads(filecontents.decode())
                newmodel = bgmodel.BgModel.buildfromdict(rawmodel)
            except BaseException as e:
                flash("Error raised parsing input file: '%s'"%e,"danger")
                return redirect(url_for('index'))
            if name:
                newmodel.name = name
            if simsdbview:
                newmodel.simsdb = simsdbview
            newid = self.modeldb.write_model(newmodel,temp=True)
        else:
            derivedFrom = request.values.get('derivedFrom', None)
            newmodel = self.modeldb.new_model(derivedFrom, name=name)
            newid = newmodel.id
        #todo: handle error no model returned, probably DB down
        return redirect(url_for('.editmodel', modelid=str(newid)))

    def delmodel(self):
        modelid = request.form.get('modelid',None)
        try:
            ndeleted = self.modeldb.del_model(modelid)
        except KeyError as e:
            abort(404, e)
        except ValueError as e:
            abort(403, e)

        if ndeleted == 1:
            flash("Successfully deleted model %s"%modelid,'success')
        else:
            flash("An error occurred trying to delete this model",'warning')
        return redirect(url_for('index'))

    #all endpoints build on the same route from here out
    def editmodel(self, modelid):
        """return a page with forms for model editing"""
        bypasscache = request.args.get('bypasscache',False)
        model = getmodelordie(modelid, toedit=True,
                                   bypasscache=bypasscache)
        return render_template('editmodel.html', model=model)

    def savemodel(self, modelid):
        """Save the model to the DB, making sure all edit details fields
        validated
        """
        model = getmodelordie(modelid, toedit=True)
        form = forms.SaveModelForm(request.form, obj=model, prefix='savemodel')
        if request.method == 'POST' and form.validate():
            form.populate_obj(model)
            # make sure the simulation data is updated
            simsdb = get_simsdb(model=model)
            error = ""
            if not simsdb:
                error += " No registered SimulationsDB"
            try:
                # temporarily force update always
                #update = form.updatesimdata.data
                update = True
                simsdb.updatesimdata(model, attach=True,
                                     findnewmatches=update, findnewdata=update)
            except units.errors.DimensionalityError as e:
                error += " Invalid unit settings: '%s'"%e
            # make sure the model is valid
            if error or not model.validate():
                flash("The model failed to validate: %s"%error,'error')
                return url_for('.editmodel', modelid=modelid, bypasscache=True)
            self.modeldb.write_model(model, temp=False, bumpversion="major")
            flash("Model '%s' successfully saved"%(model.name),
                  'success')
            return redirect(url_for("index"))

        #we should only get here if the form failed...
        return redirect(url_for('.editmodel', modelid=modelid))

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
        model = getmodelordie(modelid, toedit=True)
        clonefrom = request.values.get('clonefrom')
        if clonefrom:
            oldcomp = getcomponentordie(model, clonefrom)
            newcomp = oldcomp.clone()
        else:
            newcomp = (Assembly() if request.values.get('class') == 'Assembly'
                       else Component())
        parentid = request.values.get('parent')
        if parentid:
            parent = getcomponentordie(model, parentid)
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
        model = getmodelordie(modelid, toedit=True)
        component = getcomponentordie(model, componentid)
        model.delcomponent(componentid)
        self.modeldb.write_model(model)
        return redirect(url_for('.editmodel', modelid=modelid))

    def newplacement(self, modelid, parentid, childid):
        model = getmodelordie(modelid, toedit=True)
        parent = getcomponentordie(model, parentid)
        child = getcomponentordie(model, childid)
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
        model = getmodelordie(modelid, toedit=True)
        parent = getcomponentordie(model, parentid)
        parent.delcomponent(index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid,
                                componentid=parentid))

    def newspec(self, modelid):
        model = getmodelordie(modelid, toedit=True)
        newspec = None
        clonefrom = request.values.get('clonefrom')
        if clonefrom:
            prior = getspecordie(model, clonefrom)
            newspec = prior.clone()
        else:
            spectype = request.values.get('type', 'RadioactiveContam')
            if spectype not in self.specregistry:
                abort(404, "Unknown EmissionSpec type ", spectype)
            newspec = self.specregistry[spectype].cls()

        model.specs[newspec.id] = newspec
        self.modeldb.write_model(model)
        return redirect(url_for('.editspec',modelid=modelid, specid=newspec.id))

    def delspec(self, modelid, specid):
        model = getmodelordie(modelid, toedit=True)
        spec = getspecordie(model, specid)
        model.delspec(specid)
        self.modeldb.write_model(model)
        return redirect(url_for('.editmodel', modelid=modelid))

    def attachspec(self, modelid, compid, specid):
        model = getmodelordie(modelid, toedit=True)
        comp = getcomponentordie(model, compid)
        spec = getspecordie(model, specid)
        index = request.values.get('index')
        comp.addspec(spec, index=index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid,
                                componentid=compid))

    def detachspec(self, modelid, compid, index):
        model = getmodelordie(modelid, toedit=True)
        comp = getcomponentordie(model, compid)
        comp.delspec(index)
        self.modeldb.write_model(model)
        return redirect(url_for('.editcomponent', modelid=modelid,
                                componentid=compid))

    def setquerymod(self, modelid, compid, specid):
        model = getmodelordie(modelid, toedit=True)
        comp = getcomponentordie(model, compid)
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
        model = getmodelordie(modelid, toedit=True)
        comp = getcomponentordie(model, componentid)
        form = forms.get_form(request.form, comp)
        if request.method == 'POST':
            if form.validate():
                form.populate_obj(comp)
                #make sure the fully assembled object works
                for bs in comp.specs:
                    bs.spec = model.specs.get(bs.spec, bs.spec)
                if hasattr(comp, 'components'):
                    for plc in comp.components:
                        sub = plc.component
                        plc.component = model.components.get(sub, sub)

                status = comp.getstatus()
                if not status:
                    #no errors, so save
                    # sim data associations almost all get out of whack when
                    # anything is changed, so take the heavy-handed method of
                    # deleting all
                    for match in model.getsimdata(rootcomponent=comp):
                        del model.simdata[match.id]
                    self.modeldb.write_model(model)
                    flash("Changes to component '%s' successfully saved"%
                          comp.name, 'success')
                    return redirect(url_for('.editcomponent',
                                            modelid=modelid,
                                            componentid=componentid))
                else:
                    flash("Form validation failed. Correct errors and resubmit",
                          "danger")
                    form.specs.errors.append(status)
            else:
                flash("Form validation failed. Correct errors and resubmit",
                      "danger")

        self.addlinks(form, modelid)
        return render_template('editmodel.html', model=model,
                               editcomponent=comp, form=form)

    def editspec(self, modelid, specid):
        """return a page with forms for componentspec editing"""
        model = getmodelordie(modelid, toedit=True)
        spec = getspecordie(model, specid)
        #find the correct form
        possibleforms = [entry.form for entry in self.specregistry.values()
                         if entry.cls == type(spec)]
        if len(possibleforms) < 1:
            abort(404,"No form defined for class %s",type(spec).__name__)
        form = possibleforms[0](request.form, obj=spec)
        if request.method == 'POST':
            if form.validate():
                form.populate_obj(spec)
                #make sure the fully assembled spec works
                status = spec.getstatus()
                if not status:
                    #no errors, so save
                    # sim data associations almost all get out of whack when
                    # anything is changed, so take the heavy-handed method of
                    # deleting all
                    for match in model.getsimdata(rootspec=spec):
                        del model.simdata[match.id]
                    self.modeldb.write_model(model)
                    flash("Changes to spec '%s' successfully saved"%spec.name,
                          'success')
                    return redirect(url_for('.editspec',
                                            modelid=modelid, specid=specid))
                else:
                    flash("Form validation failed. Correct errors and resubmit",
                          "danger")
                    form.normfunc.errors.append(status)
            else:
                flash("Form validation failed. Correct errors and resubmit",
                      "danger")
        self.addlinks(form, modelid)
        return render_template('editmodel.html', model=model, editspec=spec,
                               form=form)

    def bindsimdata(self, modelid):
        """Look for updated simulation data and return a highlight view
        Confirm whether to save new bindings or cancel.

        TODO: This seems like the place to implement manual binding
        """
        model = getmodelordie(modelid, toedit=False)
        if request.method == 'POST' and request.form:
            dbname = request.form.get('simsdb')
            if dbname:
                model.simsdb = dbname
        simsdb = get_simsdb(model=model)
        if not simsdb:
            abort(501, "No registered SimulationsDB")

        try:
            matches = simsdb.updatesimdata(model)
        except units.errors.DimensionalityError as e:
            abort(400,"Invalid unit settings: '%s'"%e)
        #form = forms.BindSimDataForm(request.form)
        if request.method == 'POST' and request.form.get('confirm'): # and form.validate():
            self.modeldb.removecache(model.id)
            istemp = self.modeldb.is_model_temp(modelid)
            model.simdata = {m.id : m for m in matches}
            try:
                newid = str(self.modeldb.write_model(model,
                                                     bumpversion="minor",
                                                     temp=istemp))
            except Exception as e:
                abort(501, 'Error saving model: %s'%e)
            if istemp:
                return redirect(url_for('.editmodel', modelid=newid))
            else:
                #TODO: add a url for viewmodel here
                return redirect(url_for('modelviewer.overview',modelid=newid))
                #sort the requests by spec and assembly

        return render_template('bindsimdata.html', model=model,
                               matches=matches)


