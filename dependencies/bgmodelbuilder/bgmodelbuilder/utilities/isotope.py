""" Utility functions to convert between isotope names and Z, A """

from .elements import ELEMENTS
import re

class Isotope(object):
    """ Simple class to hold symbol, Z, and A for a nuclear isotope
    Properties:
        symbol (str): Atomic symbol
        Z (int):      Atomic number
        A (int):      Isotope mass
    Args:
        name_symbol_Z: Can be either the full name of the isotope (e.g. U238),
                       atomic symbol (e.g. 'U') or atomic number Z (e.g. 92).
                       If symbol or Z, then A must also be provided. 
                       Valid full name formats are:
                       1) {A}{symbol} e.g. 238U
                       2) {symbol}{A} e.g. U238
                       3) {symbol}{A} e.g. U-238
        A (int): atomic weight (number of nucleons), e.g. 238 for U238. 
                 Must be provided if first argument is not a full name.
    """
    _namepattern1 = re.compile(r'^(?P<A>[0-9]{1,3})(?P<symbol>[A-Z][a-z]?)$')
    _namepattern2 = re.compile(r'^(?P<symbol>[A-z][a-z]?)-?(?P<A>[0-9]{1,3})$')
    
    def __init__(self, name_symbol_Z, A=None):
        self.symbol = None
        self.Z = None
        self.A = None

        arg1 = name_symbol_Z #just to make it shorter...
        try:
            self.Z = int(arg1)
            self.A = int(A)
        except (ValueError, TypeError): #arg1 is not an integer
            pass
        else:
            self.symbol = ELEMENTS[Z].symbol
            
        if not self.Z and isinstance(arg1, str):
            # see if we match either of the full name patterns
            for test in (self._namepattern1, self._namepattern2):
                match = test.fullmatch(arg1)
                if match:
                    self.symbol = match.group('symbol')
                    self.A = int(match.group('A'))
                    break
            if not self.symbol:
                # assume arg1 is just the symbol
                self.symbol = arg1
                try:
                    self.A = int(A)
                except (ValueError, TypeError):
                    pass
            try:
                self.Z = ELEMENTS[self.symbol].number
            except KeyError:
                pass


    def format(self, fmtstr):
        """ Convert to a string according to `fmtstr`. 
        Use {symbol}, {Z}, and {A} within `fmtstr`
        """
        return fmtstr.format(**self.__dict__)
            
    default_name_format = "{symbol}{A}"
    @property
    def name(self):
        return self.format(self.default_name_format)
            

    def __eq__(self, other):
        if isinstance(other, str):
            other = Isotope(other)
        return (isinstance(other, Isotope) and 
                other.Z == self.Z and other.A == self.A)



