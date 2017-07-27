"""
The bgmodelbuilder module.

This provides classes used to represent a radiation detector and associated
radioactive background emitters.
"""

import pint

units = pint.UnitRegistry()
units.DimensionalityError = pint.errors.DimensionalityError
units.default_format = 'P'

#some common unit conversions
units.ppb_U = 12*units['mBq/kg']
units.ppb_Th = 4.1*units['mBq/kg']
units.ppb_K = 0.031*units['mBq/kg']

from . import component
from . import compspec
from . import simulationsdb
