from flask import current_app, abort


#todo: should we raise aborts on failure? 
def get_simsdb(app=current_app):
    """Get the simulations database object"""
    if not app:
        return None
    return app.extensions.get('SimulationsDB', None)

def get_modeldb(app=current_app):
    """Get the model database object"""
    if not app:
        return None
    return app.extensions.get('ModelDB', None)

def getmodelordie(query, modeldb=None, toedit=False, bypasscache=False):
    modeldb = modeldb or get_modeldb()
    if not modeldb:
        abort(501, "No registered model database")
    if toedit:
        bypasscache=True
    model = modeldb.get_model(query, bypasscache=bypasscache)
    if not model:
        abort(404, "Model not found for query %s"%query)
    if toedit and not modeldb.is_model_temp(model.id):
        abort(403, "Can not edit non-temporary model")
    return model
    
def getcomponentordie(model, compid):
    """try to find the component with ID compid in model or return 404"""
    comp = model.components.get(compid)
    if not comp:
        abort(404, "Model %s has no component with ID %s" 
              %(model._id, compid))
    return comp

def getspecordie(model, specid):
    """try to find the emissionspec with ID specid in model or return 404"""
    spec = model.specs.get(specid)
    if not spec:
        abort(404, "Model %s has no component spec with ID %s" %
              (model._id, specid))
    return spec

def getdatasetordie(datasetid, simsdb=None):
    simsdb = simsdb or get_simsdb()
    if not simsdb:
        abort(501, "No registered simulations database")
    return simsdb.getdatasetdetails(dataset)

def getsimdatamatchordie(model, matchid):
    """try to find the SimDataMatch with matchid or return 404"""
    match = model.simdata.get(matchid)
    if not match:
        abort(404, "Model %s has no SimDataMatch with ID %s" %
              (model._id, specid))
    return match

def getobjectid(obj):
    """Try to get the id of an object or dict"""
    try:
        return obj.id
    except AttributeError:
        try:
            return obj.get('id', obj.get('_id', None))
        except AttributeError:
            pass
    return obj
