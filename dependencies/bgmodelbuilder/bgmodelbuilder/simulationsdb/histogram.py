import operator
from collections import namedtuple

class Histogram(namedtuple('Histogram',('hist', 'bin_edges'))):
    """2-tuple mimicking np.histogram structure, with operator overloads
    so that bins are not added/scaled etc 
    """
    def integrate(self, a, b, binwidth=True):
        """Integrate the histogram from a to b. If a and b do not correspond to 
        exact bin edges, the value in the bin will be interpolated. 

        Args:
            a (float): low range. If bin_edges has units, this must have the 
                       same dimensionality. IF bin_edges is None, this will
                       be treated as a bin index. 
            b (float): upper edge
            binedges (bool): if True (default), multiply each bin by the bin
                             width. If False, just add bin values
        """
        bins = self.bin_edges or np.arange(len(self.spectrum)+1)
        spec = self.hist
        if b<=a or a < bins[0] or b > bins[-1]:
            raise ValueError("Integration range %s outside of defined bins"
                             %((a,b)))
        if binwidth:
            spec = spec * (bins[1:]-bins[:-1]) 
        
        first = bins.searchsorted(a,"right")
        last = bins.searchsorted(b,"left")
        #take fractions of the first and last bins
        if first == last:
            return (b-a)/(bins[first]-bins[first-1])
        return ( spec[first-1] * (bins[first]-a)/(bins[first]-bins[first-1])
                 +spec[last-1] * (b-bins[last-1])/(bins[last]-bins[last-1])
                 +sum(spec[first:min(last-2,first)])
             )

    def average(self, a, b, binwidths=True):
        """Calculate the average from a to b. See `integrate` for description
        of the arguments
        """
        return self.integrate(a, b, binwidths) / (b-a)

    
    def _testbins(self, other):
        try:
            otherbins = other.bin_edges
        except AttributeError:
            return self.bin_edges
        if otherbins is None:
            return self.bin_edges
        elif self.bin_edges is None:
            return otherbins
        elif self.bin_edges != otherbins:
            msg = ("Can't combins histograms with different binning: %s and %s"
                   %(self.bin_edges, otherbins))
            raise ValueError(msg)
        return self.bin_edges

    def _combine(self, other, op, inplace=False):
        #make sure bins are equal 
        bins = self._testbins(other)

        try:
            otherhist = other.hist
        except AttributeError:
            #how to tell the difference between a 2-tuple and 1D array???
            otherhist = other
        
        if inplace:
            op(self.hist, otherhist)
            return self
        else:
            return self.__class__(op(self.hist,otherhist), bins)

        
    #todo: should we provide for adding raw spectra rather than just Histograms?
    #binary copy operators    
    def __add__(self, other):
        return self._combine(other, operator.add)
     
    def __sub__(self, other):
        return self._combine(other, operator.sub)
    
    def __mul__(self, other):
        return self._combine(other, operator.mul)
    
    def __floordiv__(self, other):
        return self._combine(other, operator.floordiv)
    
    def __truediv__(self, other):
        return self._combine(other, operator.truediv)
    
    def __mod__(self, other):
        return self._combine(other, operator.mod)
    
    def __pow__(self, other):
        return self._combine(other, operator.pow)
    
    #do we need logical/bitwise operators??
        
    #binary in-place operators
    def __iadd__(self, other):
        return self._combine(other, operator.add, inplace=True)
     
    def __isub__(self, other):
        return self._combine(other, operator.sub, inplace=True)
    
    def __imul__(self, other):
        return self._combine(other, operator.mul, inplace=True)
    
    def __ifloordiv__(self, other):
        return self._combine(other, operator.floordiv, inplace=True)
    
    def __itruediv__(self, other):
        return self._combine(other, operator.truediv, inplace=True)
    
    def __imod__(self, other):
        return self._combine(other, operator.mod, inplace=True)
    
    def __ipow__(self, other):
        return self._combine(other, operator.pow, inplace=True)

    #reverse binary operators
    #these should only ever be called if type(other) != type(self)
    def __radd__(self, other):
        return self.__class__(other + self.hist, self.bin_edges)
     
    def __rsub__(self, other):
        return self.__class__(other - self.hist, self.bin_edges)
    
    def __rmul__(self, other):
        return self.__class__(other * self.hist, self.bin_edges)
    
    def __rfloordiv__(self, other):
        return self.__class__(other // self.hist, self.bin_edges)
    
    def __rtruediv__(self, other):
        return self.__class__(other / self.hist, self.bin_edges)
    
    def __rmod__(self, other):
        return self.__class__(other % self.hist, self.bin_edges)
    
    def __rpow__(self, other):
        return self.__class__(other ** self.hist, self.bin_edges)
    
    
    
    #unary operators
    def __neg__(self):
        return self.__class__(-self.hist, self.bin_edges)
    
    def __abs__(self):
        return self.__class__(abs(self.hist), self.bin_edges)
        
    
    
    
