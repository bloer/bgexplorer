#!/usr/bin/env python

""" simple1.py

A simple example of a background model. The example uses: 
  - An Assembly with 3 components, bulk U, Th specifications for each
  - A mongosimsdb (with default settings on localhost) populated 
    with 10 entries, 5 each U, Th split between 'bulk' and 'surface' 
    - each entry contains a 'fractionHit' value
  
  - timing is used to check the cache performance
"""
#pythom 2+3 compatibility
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import pymongo
from time import time
import timeit

import setuppath
from bgmodelbuilder.component import Assembly, Component
from bgmodelbuilder.compspec import RadioactiveContam
from bgmodelbuilder import units
from bgmodelbuilder.simulationsdb.mongosimsdb import MongoSimsDB

#build the model Assembly
model = Assembly('detector', components=[
    Component('cryostat', mass=100*units.kg, surface_in=2*units['m**2'],
              material='titanium', specs=[
        RadioactiveContam('U238', distribution='bulk', rate=10*units['mBq/kg']),
        RadioactiveContam('Th232', distribution='bulk', rate=5*units['mBq/kg']),
        RadioactiveContam('Pb210', distribution='surface_in', 
                          rate=10*units['microBq/cm**2']),
    ]),

    (Component('pmt', mass=2*units.kg, material='aluminum', specs=[
        RadioactiveContam('U238', distribution='bulk', rate=1*units['Bq/kg']),
        RadioactiveContam('Th232', distribution='bulk', rate=.2*units['Bq/kg']),
    ]),12), #npmts

    Component('reflector', mass=50*units.g, material='teflon', specs=[
        RadioactiveContam('U238', distribution='bulk', rate=10*units['mBq/kg']),
        RadioactiveContam('Th232', distribution='bulk', rate=9*units['mBq/kg']),
    ]),        
])

#build and fill the simulations database
db = pymongo.MongoClient().test
db.drop_collection('simulations')
for i,comp in enumerate(model.getcomponents()):
    for iso in ('U238', 'Th232', 'Pb210'):
        for dist in ('bulk', 'surface_in', 'surface_out'):
            db.simulations.insert_one({'source':iso, 'distribution': dist,
                                       'volume':comp.name,
                                       'timestamp': time(),
                                       'fractionHit':.02*(i+1)**2})


mdb = MongoSimsDB(database=db, model='simple1', lastmod=None)

slices = {
    'total':    model.passingselector(),
    'bulk':     model.passingselector(lambda c,s: s.distribution=='bulk'),
    'notbulk':  model.passingselector(lambda c,s: s.distribution!='bulk'),
    'U238':     model.passingselector(lambda c,s: s.name == 'U238'),
    'Th232':    model.passingselector(lambda c,s: s.name == 'Th232'),
    'OtherIso': model.passingselector(lambda c,s: s.name not in ('U238',
                                                                 'Th232')),
    'PMTs':      model.passingselector(lambda c,s: c.name == 'pmt'),
    'OtherComp': model.passingselector(lambda c,s: c.name != 'pmt'),
}
    

def runqueries(model, mdb):
    values = ['fractionHit']
    
    rates = { name:mdb.evaluate(values, cs) for name,cs in slices.items()}
    
    return rates
    
    
print([comp.getspecid(spec) for comp, spec, w in slices['total']])
print([comp.getspecid(spec) for comp, spec, w in slices['PMTs']])
print([comp.getspecid(spec) for comp, spec, w in slices['OtherComp']])
print(mdb.calculatecacheid(slices['total']))
print(mdb.calculatecacheid(slices['OtherComp']))



#run cache-less
nruns = 100
mdb.setmodel(model=None)
print("Running without cache: ")
print(timeit.timeit("runqueries(model, mdb)", number=nruns,
                    setup="from __main__ import runqueries, model, mdb"))

#now build a cache
mdb.setmodel('simple1')
print("Running with cache: ")
print(timeit.timeit("runqueries(model, mdb)", number=nruns,
                    setup="from __main__ import runqueries, model, mdb"))

rates = runqueries(model, mdb)

print('***************************')
print("Total Rate: {:~P}".format(rates['total']['fractionHit'].to('1/day')))
print('-----')
print("From bulk: {:~P}".format(rates['bulk']['fractionHit'].to('1/day')))
print("From surf: {:~P}".format(rates['notbulk']['fractionHit'].to('1/day')))
print('-----')
print("U238: {:~P}".format(rates['U238']['fractionHit'].to('1/day')))
print("Th232: {:~P}".format(rates['Th232']['fractionHit'].to('1/day')))
print("Other: {:~P}".format(rates['OtherIso']['fractionHit'].to('1/day')))
print('-----')
print("PMTs: {:~P}".format(rates['PMTs']['fractionHit'].to('1/day')))
print("Other: {:~P}".format(rates['OtherComp']['fractionHit'].to('1/day')))
print('***************************')
    
    
    
          
        
    
