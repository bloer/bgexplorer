""" simulationsdb.py

Defines the base class for a SimulationsDB. Methods must be overloaded by
the users' concrete derived class. 

A 'conversion efficiency' is the probability that a radioactive decay of a given
spectrum at a given location in the experiment geometry will produce an event 
of interest. Most frequently these are determined by simulations. The 
SimulationsDB tracks all known conversion effs and calculates reduced event
quantities. 
""" 

#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import super
from collections import namedtuple
from base64 import b64encode
from hashlib import md5
import logging

from .. import units
from .simdatamatch import SimDataMatch, AssemblyPath

log = logging.getLogger(__name__)

class SimulationsDB(object):
    """Abstract class to be implemented by user. 

    SimulationsDB serves 2 main purposes: 
    1. Translate requests for simulation data for a given assembly tree and 
       material spec into real database queries and find datasets matching
       those queries. 
    2. Calculate quantities (e.g. event rates) for matching datasets

    Auxiliary functions include:
    * listing the types of calculated quantities that the class knows how to 
      handle (Not yet implemented)

    TODO: Add an argument to attach a caching layer here
    
    """
    
    def __init__(self, app=None, *args, **kwargs):
        """Initialize a new DB instance. 
        Args:
            app: a Flask application object to register with
        """
        super().__init__(*args, **kwargs)
        self.app = app
        if app:
            self.init_app(app)


    def _getsimdatamatches(self, component, findnewdata=True, path=None):
        """Get all of the SimDataMatch objects for the given component
        Args:
            component (BaseComponent): root component to search for
            findnewdata (bool): if True, query the database for hits, livetime
            path (tuple): tuple of Placement objects. If not empty, then
                          `path[-1].component` must point to `component`
        Returns:
            list of SimDataMatch objects
        """
        if path is None:
            path = AssemblyPath()
        mymatches = []
        
        for spec in component.getspecs(deep=True):
            if spec.emissionrate(component):
                res = self.genqueries(SimDataMatch(path,spec), findnewdata)
                if res:
                    try:
                        mymatches.extend(res)
                    except TypeError: #res is not iterable
                        mymatches.append(res)

        if hasattr(component,'components'):
            for child in component.components:
                mymatches.extend(self._getsimdatamatches(child.component, 
                                                         findnewdata,
                                                         path+child))
        return mymatches

    def _updatestats(self, newmatch, oldmatch, copydataset=False):
        """Compare a new SimDataMatch with a previously stored one, and update
        the dataset and livetime if necessary
        Args:
            newmatch (SimDataMatch): The more recently generated object 
            oldmatch (SimDataMatch): the previously stored object
            copydataset (bool): If True, `oldmatch.dataset` will be copied 
                                to `newmatch`, and livetime will be updated
                                (scaling by the ratio of `emissionrate`
        Returns:
            `newmatch`, with the status field updated
        """
        newmatch._id = oldmatch.id    # is this a good idea?
        if copydataset:
            newmatch.dataset = oldmatch.dataset
            # update the livetime if need be
            if newmatch.emissionrate != oldmatch.emissionrate:
                if (newmatch.dataset and 
                    (not newmatch.emissionrate or not oldmatch.emissionrate)):
                    log.error(("Null emissionrate for simdatamatch %s, "
                               "unable to calculate livetime"),newmatch.id)
                    newmatch.livetime = None
                    newmatch.addstatus("error")
                else:
                    scale = oldmatch.emissionrate / newmatch.emissionrate
                    newmatch.livetime = oldmatch.livetime * scale
            else:
                newmatch.livetime = oldmatch.livetime
        else:
            if newmatch.dataset != oldmatch.dataset:
                newmatch.addstatus("datachanged")
                if not oldmatch.dataset:
                    newmatch.addstatus("dataadded")
                elif not newmatch.dataset:
                    newmatch.addstatus("dataremoved")

        if newmatch.livetime != oldmatch.livetime:
            newmatch.addstatus("livetimechanged")
            if (newmatch.livetime > oldmatch.livetime or 
                oldmatch.livetime is None):
                newmatch.addstatus("livetimeadded")
            elif (newmatch.livetime < oldmatch.livetime or 
                  newmatch.livetime is None):
                newmatch.addstatus("livetimeremoved")
        
        return newmatch

    def updatesimdata(self, model, findnewmatches=True, findnewdata=True, 
                      attach=False):
        """ Generate database queries to find simulation data for this
        model.  If a previous entry for a given query already exists, just
        update it. 

        Args:
            model (BgModel): the model to update
            findnewmatches (bool): If True, generate queries for all possible 
                                   placement, spec combinations.  If False, 
                                   only update matches that already exist
            findnewdata (bool): If False, just generate the query but don't
                                check the database for new hits
            attach (bool): If True, attach this data to `model.simdata`
        """
        #First, generate SimDataMatch objects for each path, spec
        newmatches = self._getsimdatamatches(model.assemblyroot, findnewdata)
                
        # For each match, see if one already exists in the model
        # if so, clone some of the prior data, or mark differences
        for newmatch in newmatches:
            found = False
            for oldmatch in model.getsimdata():
                if (newmatch.assemblyPath == oldmatch.assemblyPath and
                    newmatch.spec == oldmatch.spec and
                    newmatch.query == oldmatch.query):
                    # we've found a match
                    found=True
                    self._updatestats(newmatch, oldmatch, not findnewdata)
                    # there should only be one match 
                    break
            if not found:
                newmatch.addstatus('newmatch')
        if not findnewmatches:
            newmatches = [m for m in newmatches if not m.hasstatus('newmatch')]
        # do we attach it to the model, or just return?
        if attach:
            model.simdata = {m.id : m for m in newmatches}
        return newmatches

        
    def genqueries(self, request, findnewdata=True):
        """Create SimDataMatch objects with appropriate database queries 
        for the given path (list of Placements) and emission spec. 
        To be implemented by the concrete database class
        
        Args:
            request (SimDataMatch): An empty simdatamatch object, containing
                                    AssemblyPath and Emission spec to generate
                                    queries for
            findnewdata (bool): If True, the generated query should be executed
                                and the resulting dataset(s) attached to each 
                                SimDataMatch object returned, and the livetime
                                calculated appropriately.
        Returns:
            matches (list): a list of SimDataMatch objects for this request. 
        If the concrete DB doesn't know how to generate a query for these
        parameters, either return an empty list, or better yet, return 
        a list containing `request` with status containing "error" and log an 
        appropriate error message to help with debugging.  
        In some cases requests will generate more than one match, e.g. U238 
        and Th232 specs may generate both gamma and neutron emission matches. 
        Additional matches should be generated by calling `request.clone()`
        In this case, be sure to set the resulting weight appropriately. 
        """
        return NotImplementedError

        
    def evaluate(self, values, matches):
        """Evaluate the reduced sum for values over the list of emissionspecs.
        To be implemented by the concrete database instance. 

        Args:
            values (list): list of identifiers for values. E.g., names
                           of columns in the db entries
            matches (list): list of SimDataMatch objects
                            to caluclate these values for

        Returns:
            result (list): list of computed results in same order as values. 

        TODO: How to distinguish incorrect vs empty value requests?
        """
        raise NotImplementedError
                    
        
    def getdatasetdetails(self, datasetid):
        """Return an object with detailed info about a dataset
        To be implemented by the concrete database instance. 
        """
        raise NotImplementedError
    
    def defaultquery(self, request):
        """Generate the default query for the associated component, spec"""
        pass

    def runquery(self, query, projection=None, sort=None):
        """Run the query against the DB. Return a list of datasets or ids
        Args:
            query: Query to apply to the underlying database
            projection: a projection/mapping operator 
            sort: a sorting operator
        """
        pass
        
    
    def init_app(self, app):
        """Register ourselves as the official SimulationsDB extension"""
        app.extensions['SimulationsDB'] = self
