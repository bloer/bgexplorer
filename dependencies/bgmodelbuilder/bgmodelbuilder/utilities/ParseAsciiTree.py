""" ParseAsciiTree
Tool to create a bgmodelbuilder Assembly from the output of geant4
ASCIITree visualization. 
Must be level 5
"""
from ..common import units
from ..component import Component, Assembly

def readfile(filename):
    """Return an Assembly based on a geant4 AsciiTree output"""
    with open(filename) as f:
        return _readfile(f)
    

def _readfile(_file):
    #need to keep track of different placements of same logical volume
    logvols = {}
    indent = 0

    for line in _file:
        if line.startswith('#'): 
            continue;
        cols = line.split(',')
        if len(cols) != 5:
            raise IOError("Expect 5 columns, got %d"%len(cols))
        phys,log,solid = cols[0].split('/')
        phys, num = phys.split(':')
        spaces = len(phys) - len(phys.lstrip(' '))
        phys = phys.strip(' "')
        log = log.strip(' "')
        
        material = cols[2].split()[-1].strip(' ()')
        volume = units(cols[3].replace('m3','m^3'))
        mass = units(cols[4])
        
